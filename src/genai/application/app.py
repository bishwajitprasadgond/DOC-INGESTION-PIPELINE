import tempfile
from pathlib import Path

from nicegui import run, ui

from ...config import settings
from ..ingestion.pipeline import run_pipeline
from ..utils.logging_config import setup_logging

setup_logging(settings.logging)

_UPLOAD_DIR = Path(tempfile.gettempdir()) / "docs_ingestion_uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@ui.page("/")
def main_page():
    ui.label("Doc Q&A Ingestion").classes("text-2xl font-bold")

    uploaded_path: dict[str, Path | None] = {"path": None}

    source_mode = ui.toggle(["Upload file", "Server path"], value="Upload file")

    def handle_upload(e):
        dest = _UPLOAD_DIR / e.name
        dest.write_bytes(e.content.read())
        uploaded_path["path"] = dest
        ui.notify(f"Uploaded {e.name}")

    with ui.column().bind_visibility_from(source_mode, "value", value="Upload file"):
        ui.upload(on_upload=handle_upload, auto_upload=True).classes("w-full")

    with ui.column().bind_visibility_from(source_mode, "value", value="Server path"):
        path_input = ui.input("Server file or folder path").classes("w-full")

    output_path_input = ui.input("Output CSV path", value="questions.csv")
    mode_select = ui.select(["append", "overwrite"], value="append", label="Mode")
    output_mode_select = ui.select(["auto", "csv", "elasticsearch"], value="auto", label="Output sink")
    questions_input = ui.number("Questions per chunk", value=settings.chunking.questions_per_chunk)
    chunk_chars_input = ui.number("Chunk max chars", value=settings.chunking.chunk_max_chars)

    result_area = ui.column()

    async def on_run():
        result_area.clear()

        if source_mode.value == "Upload file":
            if uploaded_path["path"] is None:
                ui.notify("Upload a file first", color="negative")
                return
            input_path = uploaded_path["path"]
        else:
            if not path_input.value:
                ui.notify("Enter a server path", color="negative")
                return
            input_path = Path(path_input.value)

        output_mode = None if output_mode_select.value == "auto" else output_mode_select.value

        run_button.props("loading")
        try:
            summary = await run.io_bound(
                run_pipeline,
                input_path=input_path,
                output_path=Path(output_path_input.value) if output_path_input.value else None,
                mode=mode_select.value,
                questions_per_chunk=int(questions_input.value),
                chunk_max_chars=int(chunk_chars_input.value),
                output_mode=output_mode,
            )
        except (FileNotFoundError, ValueError) as exc:
            ui.notify(str(exc), color="negative")
            return
        finally:
            run_button.props(remove="loading")

        with result_area:
            ui.label(f"Files processed: {summary['files_processed']}, skipped: {summary['files_skipped']}")
            ui.label(f"Total questions: {summary['total_questions']}")
            ui.label(f"Sink: {summary['sink']}")
            destination = summary.get("output_path") or summary.get("index_name")
            ui.label(f"Destination: {destination}")
            if summary["sink"] == "csv" and destination and Path(destination).exists():
                ui.button("Download CSV", on_click=lambda: ui.download(destination))

    run_button = ui.button("Run ingestion", on_click=on_run)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="Doc Q&A Ingestion", port=8080, reload=False)
