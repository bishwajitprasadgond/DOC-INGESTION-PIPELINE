from pathlib import Path
from typing import Literal, Optional

import config
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, model_validator

from pipeline import run_pipeline

app = FastAPI(title="Doc Q&A Ingestion API")


class GenerateRequest(BaseModel):
    folder_path: Optional[str] = None
    file_path: Optional[str] = None
    output_path: Optional[str] = None
    mode: Literal["append", "overwrite"] = "append"
    output_mode: Optional[Literal["csv", "elasticsearch"]] = None
    questions_per_chunk: Optional[int] = None
    chunk_chars: Optional[int] = None

    @model_validator(mode="after")
    def _exactly_one_source(self):
        if bool(self.folder_path) == bool(self.file_path):
            raise ValueError("Provide exactly one of folder_path or file_path")
        return self


class GenerateResponse(BaseModel):
    files_processed: int
    files_skipped: int
    total_questions: int
    sink: str
    output_path: Optional[str] = None
    index_name: Optional[str] = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest) -> dict:
    input_path = Path(request.folder_path or request.file_path)

    resolved_output_mode = request.output_mode or ("elasticsearch" if config.ELASTICSEARCH_CONFIG["enabled"] else "csv")
    if resolved_output_mode == "csv" and not request.output_path:
        raise HTTPException(status_code=400, detail="output_path is required when output_mode is 'csv'")

    try:
        return run_pipeline(
            input_path=input_path,
            output_path=Path(request.output_path) if request.output_path else None,
            mode=request.mode,
            questions_per_chunk=request.questions_per_chunk,
            chunk_max_chars=request.chunk_chars,
            output_mode=request.output_mode,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
