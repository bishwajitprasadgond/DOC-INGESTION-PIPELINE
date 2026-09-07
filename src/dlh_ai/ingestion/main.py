import argparse
import sys
from pathlib import Path

import config
from pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Q&A CSV from docx/xlsx documents.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Folder to scan recursively for .docx/.xlsx files")
    source.add_argument("--file", help="Path to a single .docx/.xlsx file")
    parser.add_argument("--output", default="questions.csv", help="Output CSV path (ignored when --output-mode elasticsearch)")
    parser.add_argument(
        "--mode",
        choices=["append", "overwrite"],
        default="append",
        help="Append to an existing output CSV, or overwrite it (default: append)",
    )
    parser.add_argument(
        "--output-mode",
        choices=["csv", "elasticsearch"],
        default=None,
        help="Where to write results (default: config.toml's elasticsearch.enabled flag)",
    )
    parser.add_argument(
        "--questions-per-chunk",
        type=int,
        default=config.QUESTIONS_PER_CHUNK,
        help="Number of Q&A pairs to generate per chunk/section",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=config.CHUNK_MAX_CHARS,
        help="Approximate max characters per chunk",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input) if args.input else Path(args.file)

    try:
        summary = run_pipeline(
            input_path=input_path,
            output_path=Path(args.output),
            mode=args.mode,
            questions_per_chunk=args.questions_per_chunk,
            chunk_max_chars=args.chunk_chars,
            output_mode=args.output_mode,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    destination = summary.get("output_path") or summary.get("index_name")
    print(
        f"\nDone. Files processed: {summary['files_processed']}, skipped: {summary['files_skipped']}, "
        f"total questions: {summary['total_questions']}. Sink: {summary['sink']} ({destination})"
    )


if __name__ == "__main__":
    main()
