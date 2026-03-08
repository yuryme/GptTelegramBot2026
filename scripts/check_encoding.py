from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET_EXTENSIONS = {".py", ".md", ".json", ".yaml", ".yml", ".toml"}
EXCLUDED_DIRS = {".git", ".venv", ".venv312", "__pycache__", ".pytest_cache", "build", "dist"}
MOJIBAKE_RE = re.compile(r"[Ѓ‚ѓ„…†‡€‰Љ‹ЊЌЋЏ™љ›њќћџ]")


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TARGET_EXTENSIONS:
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path == Path(__file__).resolve():
            continue
        files.append(path)
    return files


def has_mojibake(text: str) -> bool:
    return bool(MOJIBAKE_RE.search(text))


def main() -> int:
    errors: list[str] = []
    for file_path in iter_files():
        try:
            raw = file_path.read_bytes()
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"{file_path}: not valid UTF-8")
            continue

        if has_mojibake(text):
            errors.append(f"{file_path}: possible mojibake markers found")

    if errors:
        print("Encoding check failed:")
        for item in errors:
            print(f"- {item}")
        return 1

    print("Encoding check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
