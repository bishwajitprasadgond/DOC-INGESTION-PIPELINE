import csv
import logging
import uuid
from datetime import date
from pathlib import Path

from ...config import ElasticsearchConfig, settings
from ..utils.llm_client import get_chat_model
from .extractors import extract_document
from .generator import classify_qa_row, generate_doc_metadata, generate_qa_for_chunk

logger = logging.getLogger("docs_ingestion")

CSV_FIELDS = [
    "Document-id",
    "Document-type",
    "Document-url",
    "Ingestion-date",
    "Title",
    "Keywords",
    "Category",
    "Sub-category",
    "Serial-no",
    "Question",
    "Solutions",
]

DOC_ID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

SUPPORTED_EXTENSIONS = {".docx", ".xlsx", ".pdf"}


def document_id(path: Path) -> str:
    return str(uuid.uuid5(DOC_ID_NAMESPACE, str(path.resolve())))


def resolve_input_files(input_path: Path) -> list[Path]:
    if input_path.is_dir():
        files = []
        for ext in sorted(SUPPORTED_EXTENSIONS):
            files.extend(input_path.rglob(f"*{ext}"))
        return sorted(files)

    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {input_path.suffix}")
        return [input_path]

    raise FileNotFoundError(f"Input path not found: {input_path}")


def _resolve_row_category(chat_model, row, doc_category: str, doc_sub_category: str) -> tuple[str, str]:
    category, sub_category = row.category, row.sub_category
    if category and sub_category:
        return category, sub_category

    try:
        classified = classify_qa_row(chat_model, row.question, row.answer)
    except ValueError as exc:
        logger.warning("  failed to classify table row '%s...': %s", row.question[:60], exc)
        return category or doc_category, sub_category or doc_sub_category

    return category or classified["category"] or doc_category, sub_category or classified["sub_category"] or doc_sub_category


def process_document(
    path: Path,
    chat_model,
    questions_per_chunk: int,
    chunk_max_chars: int,
    ingestion_date: str,
) -> list[dict]:
    extraction = extract_document(path, chunk_max_chars, chat_model)
    chunks, table_qa = extraction.chunks, extraction.table_qa
    if not chunks and not table_qa:
        logger.info("  no extractable content, skipping")
        return []

    if chunks:
        sample = "\n\n".join(c.text for c in chunks)[: settings.chunking.metadata_sample_chars]
    else:
        sample = "\n".join(f"Q: {r.question}\nA: {r.answer}" for r in table_qa)[: settings.chunking.metadata_sample_chars]
    metadata = generate_doc_metadata(chat_model, sample)

    qa_pairs: list[dict] = []
    for chunk in chunks:
        try:
            generated = generate_qa_for_chunk(chat_model, chunk.section, chunk.text, questions_per_chunk)
        except ValueError as exc:
            logger.warning("  failed to generate questions for section '%s': %s", chunk.section, exc)
            continue
        for pair in generated:
            qa_pairs.append({**pair, "category": None, "sub_category": None, "serial_no": None})

    # Classified one row at a time so a single row's category never leaks into another's LLM call.
    for row in table_qa:
        category, sub_category = _resolve_row_category(chat_model, row, metadata["category"], metadata["sub_category"])
        qa_pairs.append(
            {
                "question": row.question,
                "answer": row.answer,
                "category": category,
                "sub_category": sub_category,
                "serial_no": row.serial_no or None,
            }
        )

    doc_id = document_id(path)
    ext = path.suffix.lower().lstrip(".")
    rows = []
    for serial, pair in enumerate(qa_pairs, start=1):
        rows.append(
            {
                "Document-id": doc_id,
                "Document-type": ext,
                "Document-url": str(path),
                "Ingestion-date": ingestion_date,
                "Title": metadata["title"],
                "Keywords": "; ".join(metadata["keywords"]),
                "Category": pair["category"] or metadata["category"],
                "Sub-category": pair["sub_category"] or metadata["sub_category"],
                "Serial-no": pair["serial_no"] or serial,
                "Question": pair["question"],
                "Solutions": pair["answer"],
            }
        )
    if table_qa:
        logger.info("  %d question(s) taken directly from table(s), %d generated", len(table_qa), len(qa_pairs) - len(table_qa))
    return rows


def _open_output_csv(output_path: Path, mode: str):
    append = mode == "append" and output_path.exists() and output_path.stat().st_size > 0
    if append:
        with output_path.open("r", encoding="utf-8", newline="") as existing:
            first_line = existing.readline().strip()
        if first_line != ",".join(CSV_FIELDS):
            print(f"  warning: existing header in {output_path} does not match expected columns, appending anyway")
        handle = output_path.open("a", newline="", encoding="utf-8")
        return handle, csv.DictWriter(handle, fieldnames=CSV_FIELDS)

    handle = output_path.open("w", newline="", encoding="utf-8")
    writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
    writer.writeheader()
    return handle, writer


class _CsvSink:
    def __init__(self, output_path: Path, mode: str):
        self._handle, self._writer = _open_output_csv(output_path, mode)

    def write(self, rows: list[dict]) -> None:
        self._writer.writerows(rows)
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


class _ElasticsearchSink:
    """Pushes rows into Elasticsearch as vector-searchable documents, one embedding per row."""

    def __init__(self, es_config: ElasticsearchConfig):
        from elasticsearch import helpers as es_helpers

        from ..utils.embeddings import embed_row
        from ..utils.es_client import build_es_client, ensure_index

        self._bulk = es_helpers.bulk
        self._embed_row = embed_row
        self._index_name = es_config.index_name
        self._client = build_es_client(
            host=es_config.host,
            api_key=es_config.api_key,
            request_timeout=es_config.request_timeout,
            max_retries=es_config.max_retries,
            retry_on_timeout=es_config.retry_on_timeout,
            verify_certs=es_config.verify_certs,
            connections_per_node=es_config.connections_per_node,
        )
        fields = es_config.fields or CSV_FIELDS
        ensure_index(self._client, self._index_name, es_config.index_mode, fields, settings.embeddings.dimension)

    def write(self, rows: list[dict]) -> None:
        actions = []
        for row in rows:
            doc = dict(row)
            doc["embedding"] = self._embed_row(row["Question"], row["Solutions"])
            actions.append({"_index": self._index_name, "_id": f"{row['Document-id']}-{row['Serial-no']}", "_source": doc})
        self._bulk(self._client, actions)

    def close(self) -> None:
        pass


def _open_sink(output_mode: str, output_path: Path | None, mode: str):
    if output_mode == "csv":
        return _CsvSink(output_path, mode)
    return _ElasticsearchSink(settings.elasticsearch)


def run_pipeline(
    input_path: Path,
    output_path: Path | None = None,
    mode: str = "append",
    questions_per_chunk: int | None = None,
    chunk_max_chars: int | None = None,
    output_mode: str | None = None,
) -> dict:
    if mode not in ("append", "overwrite"):
        raise ValueError(f"Invalid mode: {mode!r} (expected 'append' or 'overwrite')")

    output_mode = output_mode or ("elasticsearch" if settings.elasticsearch.enabled else "csv")
    if output_mode not in ("csv", "elasticsearch"):
        raise ValueError(f"Invalid output_mode: {output_mode!r} (expected 'csv' or 'elasticsearch')")
    if output_mode == "csv" and not output_path:
        raise ValueError("output_path is required when output_mode is 'csv'")

    questions_per_chunk = questions_per_chunk or settings.chunking.questions_per_chunk
    chunk_max_chars = chunk_max_chars or settings.chunking.chunk_max_chars
    ingestion_date = date.today().isoformat()

    def _summary(files_processed: int, files_skipped: int, total_questions: int) -> dict:
        summary = {"files_processed": files_processed, "files_skipped": files_skipped, "total_questions": total_questions, "sink": output_mode}
        if output_mode == "csv":
            summary["output_path"] = str(output_path)
        else:
            summary["index_name"] = settings.elasticsearch.index_name
        return summary

    files = resolve_input_files(input_path)
    if not files:
        logger.info("No %s files found under %s", "/".join(sorted(SUPPORTED_EXTENSIONS)), input_path)
        return _summary(0, 0, 0)

    chat_model = get_chat_model()

    files_processed = 0
    files_skipped = 0
    total_questions = 0

    sink = _open_sink(output_mode, output_path, mode)
    try:
        for path in files:
            logger.info("Processing %s ...", path)
            try:
                rows = process_document(path, chat_model, questions_per_chunk, chunk_max_chars, ingestion_date)
            except Exception as exc:
                logger.error("  error: %s, skipping file", exc)
                files_skipped += 1
                continue

            if not rows:
                files_skipped += 1
                continue

            sink.write(rows)
            files_processed += 1
            total_questions += len(rows)
            logger.info("  %d questions generated", len(rows))
    finally:
        sink.close()

    return _summary(files_processed, files_skipped, total_questions)
