# Docs Ingestion

Agentic pipeline that scans `.docx` / `.xlsx` documents and produces quiz-style
Question/Answer data, either as a CSV file or pushed into Elasticsearch as
vector-searchable documents. An OpenAI-compatible LLM (served via vLLM) is used
to generate questions from free-text sections, infer document metadata, and
fill in missing table fields; a local `sentence-transformers` model computes
embeddings when the Elasticsearch sink is used.

Runs as a CLI ([main.py](main.py)) or as a backend API ([api.py](api.py)).

## How it works

- **Free-text sections** (paragraphs/rows with no existing Q&A table): chunked
  by heading (docx) or sheet/row-batch (xlsx), then sent to the LLM to
  generate a configurable number of Q&A pairs per chunk.
- **Existing Q&A tables** (a table/sheet that already has Question + Answer
  columns): rows are extracted directly instead of regenerating questions.
  - If the table also has Category / Sub-category columns, those are used;
    otherwise the LLM classifies each row individually (one call per row, so
    one row's context never leaks into another's).
  - If it has a Serial No column, that value is kept in the output instead of
    the auto-incrementing counter.
  - If the header names aren't recognized by the built-in keyword list (e.g.
    "Prompt Text" / "Correct Reply" instead of "Question" / "Answer"), the
    LLM is given just the header row and asked to map columns before falling
    back to treating the table as plain text.
- **Output**: CSV file, or an Elasticsearch index (one document per Q&A row,
  with an `embedding` vector field).

## Requirements

```bash
pip install -r requirements.txt
```

`sentence-transformers` is only imported when the Elasticsearch sink is
actually used, so a CSV-only setup doesn't need it downloaded/working.

## Configuration — `config.toml`

All settings are loaded from [config.toml](config.toml). Secrets can be
overridden via environment variables without editing the file.

```toml
[llm]
base_url = "http://10.190.236.15:9000/api/v1"   # override: LLM_BASE_URL
api_key = "sk-..."                               # override: LLM_API_KEY
model_name = "google/gemma-4-31b-it"             # override: LLM_MODEL
max_tokens = 1024
temperature = 0.2
timeout = 60.0

[chunking]
chunk_max_chars = 3000        # approx. max chars per chunk sent to the LLM
questions_per_chunk = 3       # Q&A pairs generated per chunk
metadata_sample_chars = 4000  # text sample used to infer title/keywords/category

[embeddings]
model_name = "sentence-transformers/all-MiniLM-L6-v2"
dimension = 384
device = "cpu"

[elasticsearch]
enabled = false                # default sink: false = csv, true = elasticsearch
host = "https://localhost:9200"           # override: ELASTICSEARCH__HOST
api_key = ""                              # override: ELASTICSEARCH__API_KEY
index_name = "docs-qa"
index_mode = "create"          # "create": create the index if missing (never deletes an existing one)
                                # "append": index must already exist, else it's an error
fields = ["Document-id", "Document-type", "Document-url", "Ingestion-date",
          "Title", "Keywords", "Category", "Sub-category", "Serial-no",
          "Question", "Solutions"]
request_timeout = 30
max_retries = 3
retry_on_timeout = true
verify_certs = true
connections_per_node = 10
```

## CSV output columns

```
Document-id, Document-type, Document-url, Ingestion-date, Title, Keywords,
Category, Sub-category, Serial-no, Question, Solutions
```

## CLI usage

```bash
# Scan a folder recursively, write/append to a CSV
python main.py --input ./docs --output questions.csv

# Process a single file
python main.py --file ./docs/handbook.docx --output questions.csv

# Overwrite instead of appending
python main.py --input ./docs --output questions.csv --mode overwrite

# Push straight to Elasticsearch instead of CSV
python main.py --input ./docs --output-mode elasticsearch

# Tune chunking/generation
python main.py --input ./docs --output questions.csv --questions-per-chunk 5 --chunk-chars 2000
```

| Flag | Description |
|---|---|
| `--input <folder>` | Recursively scan a folder for `.docx`/`.xlsx` (mutually exclusive with `--file`) |
| `--file <path>` | Process a single `.docx`/`.xlsx` file |
| `--output <path>` | CSV output path (default `questions.csv`; ignored when `--output-mode elasticsearch`) |
| `--mode {append,overwrite}` | CSV write mode (default `append`) |
| `--output-mode {csv,elasticsearch}` | Output sink (default: `elasticsearch.enabled` in `config.toml`) |
| `--questions-per-chunk <n>` | Override `chunking.questions_per_chunk` |
| `--chunk-chars <n>` | Override `chunking.chunk_max_chars` |

## Backend API

The same pipeline is exposed as a synchronous FastAPI service — a request
blocks until the run finishes and returns a summary.

### Run it

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Add `--reload` during local development:

```bash
uvicorn api:app --reload --port 8000
```

Interactive docs are auto-generated by FastAPI at `http://localhost:8000/docs`.

### `GET /health`

Liveness check.

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok"}
```

### `POST /generate`

Runs the pipeline once and returns a summary. Provide **exactly one** of
`folder_path` / `file_path`.

**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `folder_path` | string | one of `folder_path`/`file_path` | recursively scanned |
| `file_path` | string | one of `folder_path`/`file_path` | single `.docx`/`.xlsx` |
| `output_path` | string | required if the resolved sink is `csv` | ignored for `elasticsearch` |
| `mode` | `"append"` \| `"overwrite"` | no (default `"append"`) | CSV only |
| `output_mode` | `"csv"` \| `"elasticsearch"` | no | defaults to `elasticsearch.enabled` in `config.toml` |
| `questions_per_chunk` | int | no | overrides `config.toml` |
| `chunk_chars` | int | no | overrides `config.toml` |

**Example — folder scan to CSV**

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
        "folder_path": "./docs",
        "output_path": "questions.csv",
        "mode": "append"
      }'
```

```json
{
  "files_processed": 3,
  "files_skipped": 0,
  "total_questions": 42,
  "sink": "csv",
  "output_path": "questions.csv",
  "index_name": null
}
```

**Example — single file to CSV**

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
        "file_path": "./docs/handbook.docx",
        "output_path": "questions.csv"
      }'
```

**Example — push to Elasticsearch**

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
        "folder_path": "./docs",
        "output_mode": "elasticsearch"
      }'
```

```json
{
  "files_processed": 3,
  "files_skipped": 0,
  "total_questions": 42,
  "sink": "elasticsearch",
  "output_path": null,
  "index_name": "docs-qa"
}
```

**Error responses**

- `422 Unprocessable Entity` — request body failed validation (e.g. both or
  neither of `folder_path`/`file_path` given).
- `400 Bad Request` — application-level error (path not found, unsupported
  file type, `output_path` missing when the sink is `csv`, invalid
  `elasticsearch.index_mode`, etc.), with the reason in `detail`.

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"output_path": "questions.csv"}'
# -> 422, neither folder_path nor file_path given

curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"folder_path": "./does-not-exist", "output_path": "questions.csv"}'
# -> 400 {"detail": "Input path not found: does-not-exist"}
```

## Interactive notebook

[notebook.ipynb](notebook.ipynb) exercises the running API cell-by-cell with
`requests`: health check, single-file/folder-scan CSV generation, an
Elasticsearch push, the `422`/`400` error cases, and reading the resulting CSV
back with `pandas`. Start the server (`uvicorn api:app --port 8000`), then
open and run the notebook top to bottom.

## Project layout

| File | Purpose |
|---|---|
| [config.py](config.py) / [config.toml](config.toml) | Configuration loading |
| [extractors.py](extractors.py) | `.docx`/`.xlsx` parsing, chunking, Q&A table detection |
| [generator.py](generator.py) | LLM prompts (metadata, per-row classification, header mapping, Q&A generation) |
| [llm_client.py](llm_client.py) | Chat model factory + strict-JSON invocation helper |
| [embeddings.py](embeddings.py) | Local sentence-transformers embedding model |
| [es_client.py](es_client.py) | Elasticsearch client factory + index creation |
| [exceptions.py](exceptions.py) | `RagConfigurationError`, `ElasticsearchConnectionError` |
| [pipeline.py](pipeline.py) | Shared orchestration used by both the CLI and the API |
| [main.py](main.py) | CLI entry point |
| [api.py](api.py) | FastAPI backend |
