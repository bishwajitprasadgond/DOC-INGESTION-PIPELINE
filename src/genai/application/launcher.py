import os
import subprocess
import time
from pathlib import Path

import requests

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_UI_MODULE = "src.genai.application.app"
_BACKEND_MODULE = "src.genai.api:app"

_BACKEND_PORT = os.environ.get("CB_BACKEND_PORT", "8000")
_UI_PORT = os.environ.get("CDSW_APP_PORT", "8080")


def _check_backend(port: str) -> bool:
    try:
        requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
        return True
    except requests.exceptions.RequestException:
        return False


def launch() -> None:
    """Start the FastAPI backend and the NiceGUI UI as sibling processes, then block until interrupted."""
    env = os.environ.copy()
    env["CB_BACKEND_URL"] = f"http://127.0.0.1:{_BACKEND_PORT}"
    env["CDSW_APP_PORT"] = _UI_PORT

    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_PROJECT_ROOT}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(_PROJECT_ROOT)
    )

    print("Starting Doc Q&A Ingestion suite...")

    backend_proc: subprocess.Popen | None = None
    ui_proc: subprocess.Popen | None = None

    try:
        print(f" Launching backend (FastAPI) on port {_BACKEND_PORT}...")
        backend_proc = subprocess.Popen(
            ["python", "-m", "uvicorn", _BACKEND_MODULE, "--host", "127.0.0.1", "--port", _BACKEND_PORT],
            cwd=_PROJECT_ROOT,
            env=env,
        )

        print(" Waiting for backend health-check...")
        for attempt in range(1, 6):
            if backend_proc.poll() is not None:
                print("\n X ERROR: Backend crashed during startup. Check logs above.")
                return
            if _check_backend(_BACKEND_PORT):
                print(" Backend health-check: OK")
                break
            print(f" Waiting for backend... (attempt {attempt}/5)")
            time.sleep(3)
        else:
            print(" Backend not responding after 5 attempts, starting UI anyway.")

        print(f" Launching UI (NiceGUI) on port {_UI_PORT}...")
        ui_proc = subprocess.Popen(
            ["python", "-m", _UI_MODULE],
            cwd=_PROJECT_ROOT,
            env=env,
        )

        print("\n" + "=" * 60)
        print(" DOC Q&A INGESTION - SYSTEMS STARTED")
        print(f" Backend API : http://127.0.0.1:{_BACKEND_PORT}")
        print(f" API Docs    : http://127.0.0.1:{_BACKEND_PORT}/docs")
        print(f" Frontend UI : http://127.0.0.1:{_UI_PORT}")
        print("=" * 60)
        print("\n Use the CML-provided link for the UI port to open the app.")
        print(" Press Ctrl+C to stop both servers.\n")

        while True:
            time.sleep(1)
            if backend_proc.poll() is not None:
                print("\n BACKEND CRASHED! Check logs above.")
                break
            if ui_proc.poll() is not None:
                print("\n UI SERVER CRASHED! Check logs above.")
                break

    except KeyboardInterrupt:
        print("\nShutting down Doc Q&A Ingestion suite...")
    finally:
        if backend_proc is not None:
            backend_proc.terminate()
        if ui_proc is not None:
            ui_proc.terminate()
        print("All processes stopped.")


if __name__ == "__main__":
    launch()
