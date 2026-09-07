# Docs Ingestion

Agentic pipeline that scans `.docx` / `.xlsx` / `.pdf` documents and produces
quiz-style Question/Answer data, either as a CSV file or pushed into
Elasticsearch as vector-searchable documents. An OpenAI-compatible LLM (served
via vLLM), wired up through [LangChain](https://python.langchain.com/), is
used to generate questions from free-text sections, infer document metadata,
and fill in missing table fields; a local `sentence-transformers` model
computes embeddings when the Elasticsearch sink is used.

Runs as a CLI, a backend API, or an interactive web UI — see
[Running it](#running-it).

## How it works

- **Free-text sections** (paragraphs/pages/rows with no existing Q&A table):
  chunked by heading (docx), page (pdf), or sheet/row-batch (xlsx), then sent
  to the LLM to generate a configurable number of Q&A pairs per chunk.
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
- **PDFs** have no table detection — every PDF is extracted as free-text
  chunks (grouped by page span) and run through the same Q&A generation path
  as a docx section.
- **Output**: CSV file, or an Elasticsearch index (one document per Q&A row,
  with an `embedding` vector field).
- **LLM calls** go through [LangChain](https://python.langchain.com/): prompts
  are `langchain_core.prompts.PromptTemplate` objects loaded from
  [prompts.toml](src/genai/prompt/prompts.toml), and responses are parsed with
  `langchain_core.output_parsers.JsonOutputParser`, retrying with a
  correction message if the model returns invalid JSON.

## Project layout

```
DOC-INGESTION-PIPELINE/
├── config.toml                    # all settings (LLM, chunking, embeddings, ES, logging)
├── requirements.txt
├── logs/                          # rotating log files (created at runtime)
└── src/
    ├── config.py                  # pydantic Settings, loads ../config.toml + env overrides
    └── genai/
        ├── main.py                 # CLI entry point
        ├── api.py                  # FastAPI backend
        ├── notebook.ipynb          # calls the running API with `requests`
        ├── data/                   # sample .docx/.xlsx/.pdf inputs
        ├── ingestion/
        │   ├── extractors.py       # .docx/.xlsx/.pdf parsing, chunking, Q&A table detection
        │   ├── generator.py        # LLM-driven metadata/classification/Q&A generation
        │   └── pipeline.py         # shared orchestration used by the CLI, API, and UI
        ├── prompt/
        │   ├── prompts.toml        # one [role] section per prompt (metadata/category/header_map/qa)
        │   └── loader.py           # loads prompts.toml into PromptTemplate objects
        ├── utils/
        │   ├── llm_client.py       # chat model factory + strict-JSON invocation helper
        │   ├── embeddings.py       # local sentence-transformers embedding model
        │   ├── es_client.py        # Elasticsearch client factory + index creation
        │   ├── exceptions.py       # RagConfigurationError, ElasticsearchConnectionError
        │   └── logging_config.py   # attaches the root logs/ file + console handlers
        └── application/
            └── app.py              # NiceGUI web UI for triggering the pipeline
```

Everything under `src/genai/` is a regular Python package and uses relative
imports (`from ..utils.llm_client import ...`), so it must be run as a module
from the **repository root**, not as a standalone script — see the commands
below.

## Requirements

```bash
pip install -r requirements.txt
```

`sentence-transformers` is only imported when the Elasticsearch sink is
actually used, so a CSV-only setup doesn't need it downloaded/working.

## Configuration — `config.toml`

All settings are loaded from [config.toml](config.toml) at the repository
root via [src/config.py](src/config.py), which parses it into a validated
pydantic `Settings` object (`from src.config import settings`). Secrets can be
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

[logging]
level = "INFO"
dir = "logs"                   # relative to the repo root
filename = "ingestion.log"
max_bytes = 5000000
backup_count = 3
```

## Prompts — `src/genai/prompt/prompts.toml`

The four LLM prompts (`metadata`, `category`, `header_map`, `qa`) live in
[prompts.toml](src/genai/prompt/prompts.toml) instead of being hard-coded in
Python. Each section has a single `template` key using the placeholders
[generator.py](src/genai/ingestion/generator.py) fills in (e.g. `{text}`,
`{question}`/`{answer}`, `{headers}`, `{section}`/`{n}`/`{text}`). Edit the
wording there to change how the LLM is instructed without touching any code —
[loader.py](src/genai/prompt/loader.py) reloads them into
`langchain_core.prompts.PromptTemplate` objects at import time.

## Logging

[logging_config.py](src/genai/utils/logging_config.py) attaches a rotating
file handler (`logs/ingestion.log` at the repo root, rotated per
`[logging]` settings) and a console handler to the shared `"docs_ingestion"`
logger. It's called once, at import time, from `main.py`, `api.py`, and
`application/app.py`, so every entry point logs to the same place.

## CSV output columns

```
Document-id, Document-type, Document-url, Ingestion-date, Title, Keywords,
Category, Sub-category, Serial-no, Question, Solutions
```

## Running it

All commands are run from the **repository root**.

### CLI

```bash
# Scan a folder recursively, write/append to a CSV
python -m src.genai.main --input src/genai/data --output questions.csv

# Process a single file (.docx/.xlsx/.pdf)
python -m src.genai.main --file src/genai/data/FAQ.pdf --output questions.csv

# Overwrite instead of appending
python -m src.genai.main --input src/genai/data --output questions.csv --mode overwrite

# Push straight to Elasticsearch instead of CSV
python -m src.genai.main --input src/genai/data --output-mode elasticsearch

# Tune chunking/generation
python -m src.genai.main --input src/genai/data --output questions.csv --questions-per-chunk 5 --chunk-chars 2000
```

| Flag | Description |
|---|---|
| `--input <folder>` | Recursively scan a folder for `.docx`/`.xlsx`/`.pdf` (mutually exclusive with `--file`) |
| `--file <path>` | Process a single `.docx`/`.xlsx`/`.pdf` file |
| `--output <path>` | CSV output path (default `questions.csv`; ignored when `--output-mode elasticsearch`) |
| `--mode {append,overwrite}` | CSV write mode (default `append`) |
| `--output-mode {csv,elasticsearch}` | Output sink (default: `elasticsearch.enabled` in `config.toml`) |
| `--questions-per-chunk <n>` | Override `chunking.questions_per_chunk` |
| `--chunk-chars <n>` | Override `chunking.chunk_max_chars` |

### Backend API

The same pipeline is exposed as a synchronous FastAPI service — a request
blocks until the run finishes and returns a summary.

```bash
uvicorn src.genai.api:app --host 0.0.0.0 --port 8000

# with auto-reload during local development
uvicorn src.genai.api:app --reload --port 8000
```

Interactive docs are auto-generated by FastAPI at `http://localhost:8000/docs`.

#### `GET /health`

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok"}
```

#### `POST /generate`

Runs the pipeline once and returns a summary. Provide **exactly one** of
`folder_path` / `file_path`.

**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `folder_path` | string | one of `folder_path`/`file_path` | recursively scanned |
| `file_path` | string | one of `folder_path`/`file_path` | single `.docx`/`.xlsx`/`.pdf` |
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
        "folder_path": "./src/genai/data",
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

**Example — single PDF to CSV**

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
        "file_path": "./src/genai/data/FAQ.pdf",
        "output_path": "questions.csv"
      }'
```

**Example — push to Elasticsearch**

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
        "folder_path": "./src/genai/data",
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

### Web UI

[application/app.py](src/genai/application/app.py) is a small
[NiceGUI](https://nicegui.io/) app (pure Python, no HTML/JS) that runs the
pipeline directly — no separate API server needed.

```bash
python -m src.genai.application.app
```

Then open `http://localhost:8080`. From the page you can:

- Provide input either by uploading a single `.docx`/`.xlsx`/`.pdf` file, or
  by typing a file/folder path that exists on the machine running the app
  (same semantics as `--file`/`--input`).
- Set the output CSV path, write mode, output sink, questions-per-chunk, and
  chunk-max-chars — all defaulted from `config.toml`.
- Click **Run ingestion** to run the pipeline (off the UI thread) and see the
  resulting summary, with a download button for the CSV when that's the sink.

Runs on port `8080` by default (or `$CDSW_APP_PORT` when set, for hosting on
Cloudera CDSW/CML), separate from the API's `8000`, so both can run at once.
On startup it retries the configured LLM endpoint up to 3 times (logged to
`logs/ingestion.log`) and starts the UI regardless of the outcome — a slow or
unreachable backend never blocks the page from loading.

### Interactive notebook

[notebook.ipynb](src/genai/notebook.ipynb) exercises the running API
cell-by-cell with `requests`: health check, single-file/folder-scan CSV
generation, an Elasticsearch push, the `422`/`400` error cases, and reading
the resulting CSV back with `pandas`. Start the server
(`uvicorn src.genai.api:app --port 8000`), then open and run the notebook top
to bottom.
