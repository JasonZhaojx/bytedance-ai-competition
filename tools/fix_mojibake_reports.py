"""Fix reports where UTF-8 Chinese was accidentally decoded as Latin-1."""

from __future__ import annotations

import sys
from pathlib import Path


def fix_text(text: str) -> str:
    try:
        return text.encode("latin1").decode("utf-8")
    except UnicodeEncodeError:
        return text


def main() -> None:
    paths = [Path(arg) for arg in sys.argv[1:]]
    if not paths:
        paths = list(Path("reports").glob("*.md"))

    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        fixed = fix_text(text)
        if fixed == text:
            print(f"[skip] {path}")
            continue
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_text(text, encoding="utf-8")
        path.write_text(fixed, encoding="utf-8")
        print(f"[fixed] {path} backup={backup}")


if __name__ == "__main__":
    main()
