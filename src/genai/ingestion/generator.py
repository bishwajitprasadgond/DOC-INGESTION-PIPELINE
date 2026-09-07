import json

from langchain_openai import ChatOpenAI

from llm_client import invoke_json

METADATA_PROMPT = """You are analyzing a business document to catalog it.
Read the excerpt below and respond with ONLY a JSON object (no markdown fences) in this exact shape:
{{"title": "<short descriptive title>", "keywords": ["<keyword1>", "<keyword2>", "..."], "category": "<broad category>", "sub_category": "<more specific sub-category>"}}

Rules:
- "title" should be a concise, human-readable title for the document (max ~12 words).
- "keywords" should be 3 to 8 relevant single/short-phrase keywords.
- "category" and "sub_category" should classify the document's subject matter (e.g. category "Finance", sub_category "Invoicing").

Document excerpt:
\"\"\"
{text}
\"\"\"
"""

CATEGORY_PROMPT = """You are cataloging a single question-and-answer pair taken from a document.
Respond with ONLY a JSON object (no markdown fences) in this exact shape:
{{"category": "<broad category>", "sub_category": "<more specific sub-category>"}}

Question: {question}
Answer: {answer}
"""

HEADER_MAP_PROMPT = """You are analyzing the header row of a table extracted from a document, to figure out which column (if any) holds which kind of data.
Header columns (0-indexed): {headers}

Respond with ONLY a JSON object (no markdown fences) in this exact shape, using the 0-indexed column position or null if that kind of column is not present:
{{"question_col": <int|null>, "answer_col": <int|null>, "category_col": <int|null>, "sub_category_col": <int|null>, "serial_col": <int|null>}}

Rules:
- "question_col" is the column holding quiz/exam questions.
- "answer_col" is the column holding the answer/response/solution to that question.
- "category_col" / "sub_category_col" classify the subject matter of the row.
- "serial_col" is a row serial/sequence number (e.g. "Sr. No", "S.No", "#").
- Only set a field if you are confident that kind of column is actually present; otherwise use null.
"""

QA_PROMPT = """You are an expert quiz writer creating study questions strictly from the provided document section.
Section title: {section}

Generate exactly {n} question-and-answer pairs grounded ONLY in the text below. Do not invent facts not present in the text.
Respond with ONLY a JSON object (no markdown fences) in this exact shape:
{{"qa_pairs": [{{"question": "<question text>", "answer": "<answer text>"}}, ...]}}

Text:
\"\"\"
{text}
\"\"\"
"""


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
