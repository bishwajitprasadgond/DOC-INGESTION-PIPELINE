"""Doc Q&A Ingestion UI - pure-stdlib HTML/CSS/JS frontend.

This module serves the same ingestion-pipeline form as ``app.py``, but using
only the Python standard library (``http.server``) instead of NiceGUI/FastAPI
- no ASGI app object, no extra dependency. It is launched standalone
(``python -m src.genai.application.app2``) or via ``launcher2.py`` as a
sibling process to the FastAPI backend, on the port supplied through the
``CDSW_APP_PORT`` environment variable (default: 8090).
"""

import itertools
import json
import logging
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from ...config import settings
from ..ingestion.pipeline import run_pipeline
from ..utils.logging_config import setup_logging

setup_logging(settings.logging)

LOGGER = logging.getLogger("docs_ingestion")

_UI_PORT = int(os.environ.get("CDSW_APP_PORT") or 8090)

_UPLOAD_DIR = Path(tempfile.gettempdir()) / "docs_ingestion_uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Ingestion runs can take minutes (LLM calls per chunk); running them directly in the
# request thread held the HTTP connection open for the whole run, which browsers/proxies
# eventually time out and close, leaving `/api/run` writing to a dead socket. Instead each
# run is a background job the client polls for status + incremental log lines.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_job_counter = itertools.count(1)
_JOB_MAX_AGE_SECONDS = 3600


def _check_backend() -> bool:
    """True if the configured LLM endpoint accepts a connection (any HTTP response counts)."""
    try:
        requests.get(settings.llm.base_url, timeout=3)
        return True
    except requests.exceptions.RequestException:
        return False


class _JobLogHandler(logging.Handler):
    """Captures log records emitted by a single run into that job's in-memory log list."""

    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "level": record.levelname,
            "message": record.getMessage(),
            "milestone": bool(getattr(record, "milestone", False)),
        }
        with _JOBS_LOCK:
            job = _JOBS.get(self.job_id)
            if job is not None:
                job["log"].append(entry)


def _prune_old_jobs() -> None:
    cutoff = time.time() - _JOB_MAX_AGE_SECONDS
    stale = [jid for jid, job in _JOBS.items() if job["status"] != "running" and job["created_at"] < cutoff]
    for jid in stale:
        del _JOBS[jid]


def _run_job(job_id: str, kwargs: dict) -> None:
    pipeline_logger = logging.getLogger("docs_ingestion")
    handler = _JobLogHandler(job_id)
    pipeline_logger.addHandler(handler)
    try:
        summary = run_pipeline(**kwargs)
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "done"
            _JOBS[job_id]["result"] = summary
    except (FileNotFoundError, ValueError) as exc:
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "error"
            _JOBS[job_id]["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - background thread has no other safety net
        LOGGER.error("Unexpected error in ingestion job %s: %s", job_id, exc)
        with _JOBS_LOCK:
            _JOBS[job_id]["status"] = "error"
            _JOBS[job_id]["error"] = str(exc)
    finally:
        pipeline_logger.removeHandler(handler)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doc Q&amp;A Ingestion</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
    background: #f9fafb;
    color: #1f2937;
  }
  .header {
    background: #0f3d6e;
    color: #fff;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 24px;
    box-shadow: 0 2px 4px rgba(0,0,0,.15);
  }
  .header .icon { font-size: 22px; }
  .header-text { display: flex; flex-direction: column; line-height: 1.25; }
  .header-title { font-size: 16px; font-weight: 600; }
  .header-subtitle { font-size: 12px; opacity: .8; }
  .header-spacer { flex: 1; }
  .badge {
    background: #1c6e8c;
    color: #fff;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12px;
    margin-right: 10px;
  }
  .status-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: #9ca3af;
    display: inline-block;
  }
  .status-dot.online { background: #2e8b57; }
  .status-dot.offline { background: #dc2626; }
  .container {
    max-width: 760px;
    margin: 0 auto;
    padding: 32px 16px 64px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .card {
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 20px;
    box-shadow: 0 1px 2px rgba(0,0,0,.05);
  }
  .card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 16px;
    font-size: 15px;
    font-weight: 600;
    color: #1f2937;
  }
  .tabs { display: flex; border-bottom: 1px solid #e5e7eb; margin-bottom: 14px; }
  .tab {
    padding: 8px 16px;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    font-size: 14px;
    color: #6b7280;
    user-select: none;
  }
  .tab.active { color: #0f3d6e; border-bottom-color: #0f3d6e; font-weight: 500; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  .hint { font-size: 13px; color: #6b7280; margin: 0 0 10px; }
  label { font-size: 12px; color: #4b5563; font-weight: 500; }
  input[type=text], input[type=number], input[type=file], select {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-size: 14px;
    background: #fff;
    color: #1f2937;
  }
  input:focus, select:focus { outline: 2px solid #0f3d6e33; border-color: #0f3d6e; }
  .row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 12px; }
  .row:last-child { margin-bottom: 0; }
  .field { flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 5px; }
  .run-row { display: flex; justify-content: flex-end; }
  button.run-btn {
    background: #0f3d6e;
    color: #fff;
    border: none;
    padding: 10px 24px;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
  }
  button.run-btn:disabled { opacity: .6; cursor: not-allowed; }
  #log-panel {
    display: none;
    background: #0f172a;
    color: #cbd5e1;
    font-family: SFMono-Regular, Consolas, Menlo, monospace;
    font-size: 12.5px;
    border-radius: 8px;
    padding: 12px 14px;
    max-height: 260px;
    overflow-y: auto;
    line-height: 1.5;
  }
  .log-line { white-space: pre-wrap; }
  .log-line.milestone { color: #5eead4; font-weight: 600; }
  .log-line.level-error { color: #fca5a5; }
  .log-line.level-warning { color: #fcd34d; }
  .result-card { border-left: 4px solid #0f3d6e; }
  .result-title { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; font-weight: 600; }
  .stats { display: flex; gap: 28px; margin-bottom: 14px; }
  .stat { text-align: center; }
  .stat .n { font-size: 24px; font-weight: 700; color: #0f3d6e; }
  .stat .n.skip { color: #9ca3af; }
  .stat .n.q { color: #1c6e8c; }
  .stat .l { font-size: 12px; color: #6b7280; }
  .meta-row { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #4b5563; margin-top: 6px; word-break: break-all; }
  .divider { border-top: 1px solid #e5e7eb; margin: 14px 0; }
  .download-row { display: flex; justify-content: flex-end; margin-top: 12px; }
  a.download-btn {
    border: 1px solid #0f3d6e;
    color: #0f3d6e;
    padding: 7px 16px;
    border-radius: 6px;
    font-size: 13px;
    text-decoration: none;
  }
  #toast {
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: #dc2626;
    color: #fff;
    padding: 12px 18px;
    border-radius: 6px;
    font-size: 14px;
    box-shadow: 0 4px 10px rgba(0,0,0,.2);
    display: none;
    max-width: 360px;
  }
  #toast.positive { background: #2e8b57; }
</style>
</head>
<body>
  <div class="header">
    <span class="icon">&#9741;</span>
    <div class="header-text">
      <span class="header-title">Doc Q&amp;A Ingestion</span>
      <span class="header-subtitle">Document-to-Question/Answer Pipeline</span>
    </div>
    <div class="header-spacer"></div>
    <span class="badge">__LLM_NAME__</span>
    <span id="status-dot" class="status-dot" title="Backend status"></span>
  </div>

  <div class="container">
    <div class="card">
      <div class="card-header">1. Input Source</div>
      <div class="tabs">
        <div class="tab active" data-tab="upload" onclick="switchTab('upload')">Upload File</div>
        <div class="tab" data-tab="path" onclick="switchTab('path')">Server Path</div>
      </div>
      <div class="tab-panel active" id="panel-upload">
        <p class="hint">Upload a single .docx / .xlsx / .pdf file</p>
        <input type="file" id="file-input" accept=".docx,.xlsx,.pdf">
      </div>
      <div class="tab-panel" id="panel-path">
        <p class="hint">Path to a file or folder on the server running this app</p>
        <input type="text" id="path-input" placeholder="e.g. src/genai/data">
      </div>
    </div>

    <div class="card">
      <div class="card-header">2. Pipeline Settings</div>
      <div class="row">
        <div class="field">
          <label>Output CSV path</label>
          <input type="text" id="output-path" value="__DEFAULT_OUTPUT_PATH__">
        </div>
        <div class="field">
          <label>Write mode</label>
          <select id="mode-select">
            <option value="append" selected>append</option>
            <option value="overwrite">overwrite</option>
          </select>
        </div>
      </div>
      <div class="row">
        <div class="field">
          <label>Output sink</label>
          <select id="output-mode-select">
            <option value="auto" selected>auto</option>
            <option value="csv">csv</option>
            <option value="elasticsearch">elasticsearch</option>
          </select>
        </div>
        <div class="field">
          <label>Questions per chunk</label>
          <input type="number" id="questions-input" min="1" value="__DEFAULT_QPC__">
        </div>
        <div class="field">
          <label>Chunk max chars</label>
          <input type="number" id="chunk-chars-input" min="100" step="100" value="__DEFAULT_CHUNK_CHARS__">
        </div>
      </div>
    </div>

    <div class="run-row">
      <button class="run-btn" id="run-btn" onclick="runIngestion()">&#9654; Run Ingestion</button>
    </div>

    <div id="log-panel"></div>

    <div id="result-area"></div>
  </div>

  <div id="toast"></div>

<script>
  let uploadedPath = null;
  let activeTab = 'upload';

  function switchTab(name) {
    activeTab = name;
    document.querySelectorAll('.tab').forEach(function (el) {
      el.classList.toggle('active', el.dataset.tab === name);
    });
    document.getElementById('panel-upload').classList.toggle('active', name === 'upload');
    document.getElementById('panel-path').classList.toggle('active', name === 'path');
  }

  function showToast(message, positive) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = positive ? 'positive' : '';
    toast.style.display = 'block';
    setTimeout(function () { toast.style.display = 'none'; }, 4000);
  }

  document.getElementById('file-input').addEventListener('change', function (evt) {
    const file = evt.target.files[0];
    if (!file) return;
    fetch('/api/upload', {
      method: 'POST',
      headers: { 'X-Filename': file.name },
      body: file,
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.error) {
          showToast(data.error, false);
          return;
        }
        uploadedPath = data.path;
        showToast('Uploaded ' + file.name, true);
      })
      .catch(function () { showToast('Upload failed', false); });
  });

  function pollHealth() {
    fetch('/api/health')
      .then(function (res) { return res.json(); })
      .then(function (data) {
        const dot = document.getElementById('status-dot');
        dot.className = 'status-dot ' + (data.status === 'ok' ? 'online' : 'offline');
      })
      .catch(function () {
        document.getElementById('status-dot').className = 'status-dot offline';
      });
  }
  pollHealth();
  setInterval(pollHealth, 20000);

  let pollTimer = null;

  function resetRunButton() {
    const btn = document.getElementById('run-btn');
    btn.disabled = false;
    btn.textContent = '▶ Run Ingestion';
  }

  function appendLogLines(lines) {
    if (!lines || !lines.length) return;
    const panel = document.getElementById('log-panel');
    lines.forEach(function (entry) {
      const div = document.createElement('div');
      let cls = 'log-line';
      if (entry.milestone) cls += ' milestone';
      if (entry.level === 'ERROR') cls += ' level-error';
      else if (entry.level === 'WARNING') cls += ' level-warning';
      div.className = cls;
      div.textContent = (entry.milestone ? '◆ ' : '') + entry.message;
      panel.appendChild(div);
    });
    panel.scrollTop = panel.scrollHeight;
  }

  function pollJob(jobId, after) {
    fetch('/api/run/status?job_id=' + encodeURIComponent(jobId) + '&after=' + (after || 0))
      .then(function (res) { return res.json(); })
      .then(function (data) {
        appendLogLines(data.log);
        if (data.status === 'running') {
          pollTimer = setTimeout(function () { pollJob(jobId, data.next_after); }, 800);
        } else if (data.status === 'done') {
          renderResult(data.result);
          resetRunButton();
        } else {
          showToast(data.error || 'Run failed', false);
          resetRunButton();
        }
      })
      .catch(function () {
        showToast('Lost connection while checking run status', false);
        resetRunButton();
      });
  }

  function runIngestion() {
    let inputPath;
    if (activeTab === 'upload') {
      if (!uploadedPath) {
        showToast('Upload a file first', false);
        return;
      }
      inputPath = uploadedPath;
    } else {
      inputPath = document.getElementById('path-input').value;
      if (!inputPath) {
        showToast('Enter a server path', false);
        return;
      }
    }

    const outputModeValue = document.getElementById('output-mode-select').value;
    const body = {
      input_path: inputPath,
      output_path: document.getElementById('output-path').value || null,
      mode: document.getElementById('mode-select').value,
      output_mode: outputModeValue === 'auto' ? null : outputModeValue,
      questions_per_chunk: parseInt(document.getElementById('questions-input').value, 10),
      chunk_max_chars: parseInt(document.getElementById('chunk-chars-input').value, 10),
    };

    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }

    const btn = document.getElementById('run-btn');
    btn.disabled = true;
    btn.textContent = 'Running...';
    document.getElementById('result-area').innerHTML = '';
    const logPanel = document.getElementById('log-panel');
    logPanel.innerHTML = '';
    logPanel.style.display = 'block';

    fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data }; }); })
      .then(function (result) {
        if (!result.ok) {
          showToast(result.data.error || 'Run failed', false);
          resetRunButton();
          return;
        }
        pollJob(result.data.job_id, 0);
      })
      .catch(function () {
        showToast('Run failed', false);
        resetRunButton();
      });
  }

  function renderResult(summary) {
    const destination = summary.output_path || summary.index_name;
    let downloadHtml = '';
    if (summary.sink === 'csv' && destination) {
      downloadHtml =
        '<div class="download-row"><a class="download-btn" href="/api/download?path=' +
        encodeURIComponent(destination) +
        '">&#8681; Download CSV</a></div>';
    }
    document.getElementById('result-area').innerHTML =
      '<div class="card result-card">' +
      '<div class="result-title">&#9989; Run complete</div>' +
      '<div class="stats">' +
      '<div class="stat"><div class="n">' + summary.files_processed + '</div><div class="l">Processed</div></div>' +
      '<div class="stat"><div class="n skip">' + summary.files_skipped + '</div><div class="l">Skipped</div></div>' +
      '<div class="stat"><div class="n q">' + summary.total_questions + '</div><div class="l">Questions</div></div>' +
      '</div>' +
      '<div class="divider"></div>' +
      '<div class="meta-row">Sink: ' + summary.sink + '</div>' +
      '<div class="meta-row">Destination: ' + destination + '</div>' +
      downloadHtml +
      '</div>';
  }
</script>
</body>
</html>
"""


def _render_page() -> bytes:
    html = _HTML_TEMPLATE
    html = html.replace("__LLM_NAME__", settings.llm.name)
    html = html.replace("__DEFAULT_OUTPUT_PATH__", "questions.csv")
    html = html.replace("__DEFAULT_QPC__", str(settings.chunking.questions_per_chunk))
    html = html.replace("__DEFAULT_CHUNK_CHARS__", str(settings.chunking.chunk_max_chars))
    return html.encode("utf-8")


_PAGE = _render_page()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        LOGGER.debug("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.warning("Client disconnected before response could be sent (%s)", self.path)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_PAGE)))
            self.end_headers()
            self.wfile.write(_PAGE)
            return

        if parsed.path == "/api/health":
            self._send_json(200, {"status": "ok" if _check_backend() else "offline"})
            return

        if parsed.path == "/api/download":
            query = parse_qs(parsed.query)
            path_values = query.get("path")
            if not path_values:
                self._send_json(400, {"error": "missing path"})
                return
            file_path = Path(path_values[0])
            if not file_path.is_file():
                self._send_json(404, {"error": f"file not found: {file_path}"})
                return
            data = file_path.read_bytes()
            self.send_response(200)
            content_type = "text/csv" if file_path.suffix.lower() == ".csv" else "application/octet-stream"
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if parsed.path == "/api/run/status":
            query = parse_qs(parsed.query)
            job_id = (query.get("job_id") or [None])[0]
            after = int((query.get("after") or ["0"])[0])
            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                if job is None:
                    self._send_json(404, {"error": "unknown job_id"})
                    return
                new_log = job["log"][after:]
                payload = {"status": job["status"], "log": new_log, "next_after": len(job["log"])}
                if job["status"] == "done":
                    payload["result"] = job["result"]
                elif job["status"] == "error":
                    payload["error"] = job["error"]
            self._send_json(200, payload)
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""

        if parsed.path == "/api/upload":
            filename = Path(self.headers.get("X-Filename", "upload.bin")).name
            if not filename:
                self._send_json(400, {"error": "missing X-Filename header"})
                return
            dest = _UPLOAD_DIR / filename
            dest.write_bytes(raw)
            self._send_json(200, {"path": str(dest.resolve())})
            return

        if parsed.path == "/api/run":
            try:
                body = json.loads(raw or b"{}")
                output_path = body.get("output_path")
                kwargs = dict(
                    input_path=Path(body["input_path"]),
                    output_path=Path(output_path) if output_path else None,
                    mode=body.get("mode", "append"),
                    questions_per_chunk=body.get("questions_per_chunk"),
                    chunk_max_chars=body.get("chunk_max_chars"),
                    output_mode=body.get("output_mode"),
                )
            except (json.JSONDecodeError, KeyError) as exc:
                self._send_json(400, {"error": f"invalid request: {exc}"})
                return

            job_id = str(next(_job_counter))
            with _JOBS_LOCK:
                _prune_old_jobs()
                _JOBS[job_id] = {
                    "status": "running",
                    "log": [],
                    "result": None,
                    "error": None,
                    "created_at": time.time(),
                }
            threading.Thread(target=_run_job, args=(job_id, kwargs), daemon=True).start()
            self._send_json(202, {"job_id": job_id})
            return

        self._send_json(404, {"error": "not found"})


def main() -> None:
    LOGGER.info("Doc Q&A Ingestion UI (app2) starting on port %d...", _UI_PORT)
    LOGGER.info("Backend target: %s", settings.llm.base_url)

    for attempt in range(1, 4):
        if _check_backend():
            LOGGER.info("Backend health-check: OK")
            break
        LOGGER.info("Waiting for backend... (attempt %d/3)", attempt)
        time.sleep(3)
    else:
        LOGGER.warning("Backend not responding, UI will start anyway.")

    print("CDSW_APP_PORT =", os.getenv("CDSW_APP_PORT"))
    print("CDSW_READONLY_PORT =", os.getenv("CDSW_READONLY_PORT"))
    print("CB_APP_PORT =", os.getenv("CB_APP_PORT"))
    print("UI_PORT =", _UI_PORT)
    print("CDSW_PUBLIC_PORT =", os.getenv("CDSW_PUBLIC_PORT"))
    print(f"  Doc Q&A Ingestion UI (app2)  ->  http://127.0.0.1:{_UI_PORT}")
    print(f"  Backend target                ->  {settings.llm.base_url}")
    print("  Press Ctrl+C to stop.\n")

    server = ThreadingHTTPServer(("127.0.0.1", _UI_PORT), _Handler)
    LOGGER.info("UI ready at http://127.0.0.1:%d", _UI_PORT)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
