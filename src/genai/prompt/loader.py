import tomllib
from pathlib import Path

from langchain_core.prompts import PromptTemplate

_PROMPTS_PATH = Path(__file__).resolve().parent / "prompts.toml"


def load_prompts() -> dict[str, PromptTemplate]:
    with _PROMPTS_PATH.open("rb") as f:
        raw = tomllib.load(f)
    return {name: PromptTemplate.from_template(section["template"]) for name, section in raw.items()}
