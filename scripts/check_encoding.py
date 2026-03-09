from __future__ import annotations

import argparse
import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET_EXTENSIONS = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".txt"}
NO_BOM_EXTENSIONS = {".py", ".json", ".yml", ".yaml", ".toml", ".md"}
EXCLUDED_DIRS = {".git", ".venv", ".venv312", "__pycache__", ".pytest_cache", "build", "dist", ".mypy_cache", ".ruff_cache"}
MOJIBAKE_PATTERNS = [
    # Typical UTF-8 Cyrillic decoded as cp1251/latin-1 artifacts.
    re.compile(r"Р[ЃЉЊЋЏђѓєѕіїјљњћќўџ]"),
    re.compile(r"С[ЃЉЊЋЏђѓєѕіїјљњћќўџ]"),
    re.compile(r"Ð[A-Za-z]"),
    re.compile(r"Ñ[A-Za-z]"),
]
ALLOWLIST_FILE = ROOT / "scripts" / "encoding_allowlist.txt"


@dataclass
class Issue:
    file_path: Path
    issue_type: str
    message: str
    suggestion: str


def load_allowlist() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"utf8": [], "bom": [], "mojibake": [], "all": []}
    if not ALLOWLIST_FILE.exists():
        return result

    for line in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            issue_type, pattern = line.split(":", 1)
            issue_type = issue_type.strip()
            pattern = pattern.strip()
        else:
            issue_type, pattern = "all", line
        if issue_type not in result:
            continue
        result[issue_type].append(pattern)
    return result


def is_allowed(rel_path: str, issue_type: str, allowlist: dict[str, list[str]]) -> bool:
    patterns = allowlist.get(issue_type, []) + allowlist.get("all", [])
    return any(fnmatch.fnmatch(rel_path, p) for p in patterns)


def is_binary(raw: bytes) -> bool:
    return b"\x00" in raw


def iter_text_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for base in paths:
        candidate = base if base.is_absolute() else ROOT / base
        if candidate.is_file():
            if candidate.suffix.lower() in TARGET_EXTENSIONS:
                files.append(candidate)
            continue
        if not candidate.exists():
            continue
        for path in candidate.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in TARGET_EXTENSIONS:
                continue
            if any(part in EXCLUDED_DIRS for part in path.parts):
                continue
            files.append(path)
    return files


def detect_mojibake(text: str) -> bool:
    return any(p.search(text) for p in MOJIBAKE_PATTERNS)


def check_file(file_path: Path, checks: set[str], allowlist: dict[str, list[str]]) -> list[Issue]:
    issues: list[Issue] = []
    rel_path = file_path.relative_to(ROOT).as_posix()
    raw = file_path.read_bytes()
    if is_binary(raw):
        return issues

    text = ""
    decoded_utf8 = True
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        decoded_utf8 = False
        if "utf8" in checks and not is_allowed(rel_path, "utf8", allowlist):
            issues.append(
                Issue(
                    file_path=file_path,
                    issue_type="utf8",
                    message="file is not valid UTF-8",
                    suggestion="Run: python scripts/check_encoding.py --fix --check-type utf8 --paths " + rel_path,
                )
            )

    if "bom" in checks and file_path.suffix.lower() in NO_BOM_EXTENSIONS:
        if raw.startswith(b"\xef\xbb\xbf") and not is_allowed(rel_path, "bom", allowlist):
            issues.append(
                Issue(
                    file_path=file_path,
                    issue_type="bom",
                    message="UTF-8 BOM is not allowed for this file type",
                    suggestion="Run: python scripts/check_encoding.py --fix --check-type bom --paths " + rel_path,
                )
            )

    if "mojibake" in checks and decoded_utf8:
        if detect_mojibake(text) and not is_allowed(rel_path, "mojibake", allowlist):
            issues.append(
                Issue(
                    file_path=file_path,
                    issue_type="mojibake",
                    message="possible mojibake pattern detected",
                    suggestion="Inspect and re-save file as proper UTF-8 text.",
                )
            )
    return issues


def fix_utf8(file_path: Path) -> bool:
    raw = file_path.read_bytes()
    if is_binary(raw):
        return False
    try:
        raw.decode("utf-8")
        return False
    except UnicodeDecodeError:
        pass

    # Safe legacy conversion path: cp1251 -> utf-8
    try:
        text = raw.decode("cp1251")
    except UnicodeDecodeError:
        return False
    file_path.write_text(text, encoding="utf-8", newline="\n")
    return True


def fix_bom(file_path: Path) -> bool:
    raw = file_path.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        return False
    file_path.write_bytes(raw[3:])
    return True


def run_check(files: list[Path], checks: set[str], allowlist: dict[str, list[str]]) -> tuple[int, list[Issue]]:
    issues: list[Issue] = []
    for file_path in files:
        issues.extend(check_file(file_path, checks, allowlist))
    return (1 if issues else 0), issues


def run_fix(files: list[Path], checks: set[str]) -> tuple[int, list[str]]:
    changes: list[str] = []
    for file_path in files:
        rel_path = file_path.relative_to(ROOT).as_posix()
        if "utf8" in checks and fix_utf8(file_path):
            changes.append(f"{rel_path}: converted cp1251 -> utf-8")
        if "bom" in checks and file_path.suffix.lower() in NO_BOM_EXTENSIONS and fix_bom(file_path):
            changes.append(f"{rel_path}: removed UTF-8 BOM")
    return 0, changes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Encoding guardrails checker/fixer.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Report issues and return non-zero if found.")
    mode.add_argument("--fix", action="store_true", help="Apply safe automatic fixes.")
    parser.add_argument(
        "--check-type",
        action="append",
        choices=["utf8", "bom", "mojibake"],
        help="Restrict checks/fixes to one or more issue types.",
    )
    parser.add_argument("--paths", nargs="*", default=["."], help="Paths to scan.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks = set(args.check_type or ["utf8", "bom", "mojibake"])
    files = iter_text_files([Path(p) for p in args.paths])

    if args.fix:
        _, changes = run_fix(files, checks)
        if changes:
            print("Encoding fixes applied:")
            for line in changes:
                print(f"- {line}")
        else:
            print("No automatic fixes applied.")
        return 0

    allowlist = load_allowlist()
    code, issues = run_check(files, checks, allowlist)
    if issues:
        print("Encoding check failed:")
        for item in issues:
            rel = item.file_path.relative_to(ROOT).as_posix()
            print(f"- {rel}: [{item.issue_type}] {item.message}")
            print(f"  Suggestion: {item.suggestion}")
        return 1

    print("Encoding check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
