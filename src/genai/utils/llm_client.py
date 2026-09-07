import json
import re

from langchain_openai import ChatOpenAI

from ...config import settings

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def get_chat_model() -> ChatOpenAI:
    llm = settings.llm
    return ChatOpenAI(
        base_url=llm.base_url,
        api_key=llm.api_key,
        model=llm.model_name,
        temperature=llm.temperature,
        max_tokens=llm.max_tokens,
        timeout=llm.timeout,
    )


def _clean_json_text(raw: str) -> str:
    text = raw.strip()
    text = _CODE_FENCE_RE.sub("", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return text


def invoke_json(chat_model: ChatOpenAI, prompt: str, retries: int = 2) -> dict:
    last_error: Exception | None = None
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(retries + 1):
        response = chat_model.invoke(messages)
        raw = response.content if isinstance(response.content, str) else str(response.content)
        cleaned = _clean_json_text(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            last_error = exc
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        f"That was not valid JSON ({exc}). "
                        "Reply again with ONLY the corrected JSON object, no markdown fences, no commentary."
                    ),
                },
            ]

    raise ValueError(f"LLM did not return valid JSON after {retries + 1} attempts: {last_error}")
