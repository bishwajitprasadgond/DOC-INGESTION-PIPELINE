from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI

from ...config import settings

_json_parser = JsonOutputParser()


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


def invoke_json(chat_model: ChatOpenAI, prompt: str, retries: int = 2) -> dict:
    chain = chat_model | _json_parser
    messages = [{"role": "user", "content": prompt}]
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            return chain.invoke(messages)
        except OutputParserException as exc:
            last_error = exc
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": exc.llm_output or ""},
                {
                    "role": "user",
                    "content": (
                        f"That was not valid JSON ({exc}). "
                        "Reply again with ONLY the corrected JSON object, no markdown fences, no commentary."
                    ),
                },
            ]

    raise ValueError(f"LLM did not return valid JSON after {retries + 1} attempts: {last_error}")
