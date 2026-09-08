#!/usr/bin/env python3
"""
Project Dump Utility

Usage:
    Copy this script into any project folder and run:

        python project_dump.py

Outputs:
    project_tree.txt
    project_dump.txt
"""

import os
from pathlib import Path

# ==============================================================================
# CONFIGURATION
# ==============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent

SOURCE_FOLDER = SCRIPT_DIR

OUTPUT_FILE = SCRIPT_DIR / "project_dump.txt"
TREE_FILE = SCRIPT_DIR / "project_tree.txt"

# Skip these folders
EXCLUDE_FOLDERS = {
    "__pycache__",
    ".git",
    ".github",
    ".gitlab",
    ".idea",
    ".vscode",
    ".vs",
    ".pytest_cache",
    ".mypy_cache",
    ".cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "logs",
    "log",
    "build",
    "dist",
    "target",
    "coverage",
    "out",
    "bin",
    "obj",
    ".next",
}

# Skip these files
EXCLUDE_FILES = {
    Path(__file__).name,
    OUTPUT_FILE.name,
    TREE_FILE.name,
    ".DS_Store",
    "Thumbs.db",
}

# Skip these extensions
EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".dll",
    ".exe",
    ".so",
    ".dylib",
    ".class",
    ".jar",
    ".war",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".xz",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".webp",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".mp3",
    ".wav",
    ".ogg",
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".db",
    ".sqlite",
}

MAX_FILE_SIZE_MB = 10

# ==============================================================================


def should_include(file_path: Path) -> bool:
    """Return True if file should be included."""

    if file_path.name in EXCLUDE_FILES:
        return False

    if file_path.suffix.lower() in EXCLUDE_EXTENSIONS:
        return False

    try:
        if file_path.stat().st_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            return False
    except Exception:
        return False

    return True


def build_tree(folder: Path) -> str:
    """Generate folder tree."""

    lines = []

    for root, dirs, files in os.walk(folder):

        dirs[:] = sorted(
            d for d in dirs
            if d.lower() not in {x.lower() for x in EXCLUDE_FOLDERS}
        )

        root_path = Path(root)

        level = len(root_path.relative_to(folder).parts)

        indent = "    " * level

        if root_path == folder:
            lines.append(folder.name + "/")
        else:
            lines.append(f"{indent}|-- {root_path.name}/")

        subindent = "    " * (level + 1)

        for file in sorted(files):

            path = root_path / file

            if should_include(path):
                lines.append(f"{subindent}|-- {file}")

    return "\n".join(lines)


def save_tree():
    """Save tree."""

    tree = build_tree(SOURCE_FOLDER)

    with open(TREE_FILE, "w", encoding="utf-8") as f:
        f.write(tree)

    print(f"[OK] Created: {TREE_FILE.name}")


def dump_project():
    """Dump project files."""

    tree = build_tree(SOURCE_FOLDER)

    total = 0

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:

        out.write("=" * 100 + "\n")
        out.write("PROJECT STRUCTURE\n")
        out.write("=" * 100 + "\n\n")

        out.write(tree)

        out.write("\n\n")
        out.write("=" * 100 + "\n")
        out.write("FILE CONTENTS\n")
        out.write("=" * 100 + "\n")

        for root, dirs, files in os.walk(SOURCE_FOLDER):

            dirs[:] = sorted(
                d for d in dirs
                if d.lower() not in {x.lower() for x in EXCLUDE_FOLDERS}
            )

            root_path = Path(root)

            for file in sorted(files):

                path = root_path / file

                if not should_include(path):
                    continue

                total += 1

                relative = path.relative_to(SOURCE_FOLDER)

                print(f"Reading: {relative}")

                out.write("\n")
                out.write("#" * 100 + "\n")
                out.write(f"FILE: {relative}\n")
                out.write("#" * 100 + "\n\n")

                try:
                    with open(
                        path,
                        "r",
                        encoding="utf-8",
                        errors="ignore",
                    ) as f:
                        out.write(f.read())

                except Exception as e:
                    out.write(f"ERROR READING FILE:\n{e}\n")

                out.write("\n\n")

    print()
    print("=" * 70)
    print(f"Files Dumped : {total}")
    print(f"Tree File    : {TREE_FILE.name}")
    print(f"Dump File    : {OUTPUT_FILE.name}")
    print("=" * 70)


def main():

    print("=" * 70)
    print("PROJECT DUMP UTILITY")
    print("=" * 70)
    print(f"Scanning : {SOURCE_FOLDER}")
    print()

    save_tree()

    dump_project()

    print("\nDone.")


if __name__ == "__main__":
    main()