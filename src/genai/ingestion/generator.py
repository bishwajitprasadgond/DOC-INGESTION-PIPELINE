import json

from langchain_openai import ChatOpenAI

from ..prompt.loader import load_prompts
from ..utils.llm_client import invoke_json

_prompts = load_prompts()
METADATA_PROMPT = _prompts["metadata"]
CATEGORY_PROMPT = _prompts["category"]
HEADER_MAP_PROMPT = _prompts["header_map"]
QA_PROMPT = _prompts["qa"]


def generate_doc_metadata(chat_model: ChatOpenAI, doc_text_sample: str) -> dict:
    prompt = METADATA_PROMPT.format(text=doc_text_sample)
    result = invoke_json(chat_model, prompt)
    return {
        "title": str(result.get("title", "")).strip(),
        "keywords": [str(k).strip() for k in result.get("keywords", []) if str(k).strip()],
        "category": str(result.get("category", "")).strip(),
        "sub_category": str(result.get("sub_category", "")).strip(),
    }


def classify_qa_row(chat_model: ChatOpenAI, question: str, answer: str) -> dict:
    prompt = CATEGORY_PROMPT.format(question=question, answer=answer)
    result = invoke_json(chat_model, prompt)
    return {
        "category": str(result.get("category", "")).strip(),
        "sub_category": str(result.get("sub_category", "")).strip(),
    }


def classify_table_headers(chat_model: ChatOpenAI, headers: list[str]) -> dict:
    prompt = HEADER_MAP_PROMPT.format(headers=json.dumps(headers))
    result = invoke_json(chat_model, prompt)

    def _valid_idx(value) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 0 <= value < len(headers) else None

    return {
        "question_col": _valid_idx(result.get("question_col")),
        "answer_col": _valid_idx(result.get("answer_col")),
        "category_col": _valid_idx(result.get("category_col")),
        "sub_category_col": _valid_idx(result.get("sub_category_col")),
        "serial_col": _valid_idx(result.get("serial_col")),
    }


def generate_qa_for_chunk(
    chat_model: ChatOpenAI, section_label: str, chunk_text: str, n_questions: int
) -> list[dict]:
    prompt = QA_PROMPT.format(section=section_label, n=n_questions, text=chunk_text)
    result = invoke_json(chat_model, prompt)
    pairs = []
    for item in result.get("qa_pairs", []):
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if question and answer:
            pairs.append({"question": question, "answer": answer})
    return pairs
