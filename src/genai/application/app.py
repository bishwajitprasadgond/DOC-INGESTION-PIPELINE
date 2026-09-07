import tempfile
from pathlib import Path

from nicegui import run, ui

from ...config import settings
from ..ingestion.pipeline import run_pipeline
from ..utils.logging_config import setup_logging

setup_logging(settings.logging)

_UPLOAD_DIR = Path(tempfile.gettempdir()) / "docs_ingestion_uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ui.colors(primary="#0f3d6e", secondary="#1c6e8c", accent="#2e8b57", positive="#2e8b57")


def _section(icon: str, title: str):
    with ui.card().classes("w-full shadow-sm rounded-lg border border-gray-200 p-5"):
        with ui.row().classes("items-center gap-2 mb-4"):
            ui.icon(icon).classes("text-primary text-xl")
            ui.label(title).classes("text-base font-semibold text-gray-800")
        content = ui.column().classes("w-full gap-3")
    return content


@ui.page("/")
def main_page():
    ui.query("body").classes("bg-gray-50")
    ui.add_head_html(
        "<style>.q-field__label{font-weight:500} .nicegui-content{padding:0 !important}</style>"
    )

    with ui.header().classes("bg-primary text-white items-center px-6 py-3 shadow-md"):
        ui.icon("hub").classes("text-2xl")
        with ui.column().classes("gap-0 ml-2"):
            ui.label("Doc Q&A Ingestion").classes("text-lg font-semibold leading-tight")
            ui.label("Document-to-Question/Answer Pipeline").classes("text-xs opacity-80 leading-tight")
        ui.space()
        ui.badge(f"{settings.llm.name}", color="secondary").classes("text-xs")

    uploaded_path: dict[str, Path | None] = {"path": None}

    with ui.column().classes("w-full max-w-3xl mx-auto px-4 py-8 gap-5"):
        with _section("input", "1. Input Source") as input_section:
            with input_section:
                with ui.tabs().classes("w-full") as source_tabs:
                    tab_upload = ui.tab("Upload File", icon="upload_file")
                    tab_path = ui.tab("Server Path", icon="folder_open")

                with ui.tab_panels(source_tabs, value=tab_upload).classes("w-full border rounded-md"):
                    with ui.tab_panel(tab_upload):
                        ui.label("Upload a single .docx / .xlsx / .pdf file").classes("text-sm text-gray-500 mb-2")

                        def handle_upload(e):
                            dest = _UPLOAD_DIR / e.name
                            dest.write_bytes(e.content.read())
                            uploaded_path["path"] = dest
                            ui.notify(f"Uploaded {e.name}", color="positive", icon="check_circle")

                        ui.upload(on_upload=handle_upload, auto_upload=True).classes("w-full").props(
                            "flat bordered accept=.docx,.xlsx,.pdf"
                        )

                    with ui.tab_panel(tab_path):
                        ui.label("Path to a file or folder on the server running this app").classes(
                            "text-sm text-gray-500 mb-2"
                        )
                        path_input = ui.input(placeholder="e.g. src/genai/data").classes("w-full").props(
                            "outlined dense clearable"
                        )

        with _section("tune", "2. Pipeline Settings") as settings_section:
            with settings_section:
                with ui.row().classes("w-full gap-4 flex-wrap"):
                    output_path_input = ui.input("Output CSV path", value="questions.csv").props(
                        "outlined dense"
                    ).classes("flex-1 min-w-[220px]")
                    mode_select = ui.select(["append", "overwrite"], value="append", label="Write mode").props(
                        "outlined dense"
                    ).classes("flex-1 min-w-[160px]")
                with ui.row().classes("w-full gap-4 flex-wrap"):
                    output_mode_select = ui.select(
                        ["auto", "csv", "elasticsearch"], value="auto", label="Output sink"
                    ).props("outlined dense").classes("flex-1 min-w-[160px]")
                    questions_input = ui.number(
                        "Questions per chunk", value=settings.chunking.questions_per_chunk, min=1
                    ).props("outlined dense").classes("flex-1 min-w-[160px]")
                    chunk_chars_input = ui.number(
                        "Chunk max chars", value=settings.chunking.chunk_max_chars, min=100, step=100
                    ).props("outlined dense").classes("flex-1 min-w-[160px]")

        with ui.row().classes("w-full justify-end"):
            run_button = ui.button("Run Ingestion", icon="play_arrow", on_click=lambda: on_run()).props(
                "unelevated color=primary"
            ).classes("px-6 py-2 text-sm font-medium")

        result_card = ui.column().classes("w-full")

        async def on_run():
            result_card.clear()

            if source_tabs.value == tab_upload:
                if uploaded_path["path"] is None:
                    ui.notify("Upload a file first", color="negative", icon="error")
                    return
                input_path = uploaded_path["path"]
            else:
                if not path_input.value:
                    ui.notify("Enter a server path", color="negative", icon="error")
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
                ui.notify(str(exc), color="negative", icon="error")
                return
            finally:
                run_button.props(remove="loading")

            destination = summary.get("output_path") or summary.get("index_name")
            with result_card:
                with ui.card().classes("w-full shadow-sm rounded-lg border-l-4 border-primary p-5"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("check_circle").classes("text-positive text-xl")
                        ui.label("Run complete").classes("text-base font-semibold text-gray-800")

                    with ui.row().classes("w-full gap-6"):
                        with ui.column().classes("items-center"):
                            ui.label(str(summary["files_processed"])).classes("text-2xl font-bold text-primary")
                            ui.label("Processed").classes("text-xs text-gray-500")
                        with ui.column().classes("items-center"):
                            ui.label(str(summary["files_skipped"])).classes("text-2xl font-bold text-gray-400")
                            ui.label("Skipped").classes("text-xs text-gray-500")
                        with ui.column().classes("items-center"):
                            ui.label(str(summary["total_questions"])).classes("text-2xl font-bold text-secondary")
                            ui.label("Questions").classes("text-xs text-gray-500")

                    ui.separator().classes("my-3")

                    with ui.row().classes("items-center gap-2"):
                        ui.icon("storage").classes("text-gray-400 text-sm")
                        ui.label(f"Sink: {summary['sink']}").classes("text-sm text-gray-600")
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("description").classes("text-gray-400 text-sm")
                        ui.label(f"Destination: {destination}").classes("text-sm text-gray-600 break-all")

                    if summary["sink"] == "csv" and destination and Path(destination).exists():
                        with ui.row().classes("w-full justify-end mt-3"):
                            ui.button(
                                "Download CSV", icon="download", on_click=lambda: ui.download(destination)
                            ).props("outline color=primary")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="Doc Q&A Ingestion", port=8080, reload=False)
