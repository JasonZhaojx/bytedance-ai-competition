"""Analyze one product in its own console window and save a report."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from extracted_core import product_example  # noqa: E402


class Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--done")
    args = parser.parse_args()

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    original_argv = sys.argv[:]
    sys.argv = [str(ROOT / "extracted_core" / "product_example.py"), args.product]
    os.environ["PYTHONUNBUFFERED"] = "1"

    exit_code = 0
    with report_path.open("w", encoding="utf-8", buffering=1) as report_file:
        report_file.write(f"# {args.product}\n\n")
        report_file.flush()
        tee_stdout = Tee(sys.__stdout__, report_file)
        tee_stderr = Tee(sys.__stderr__, report_file)
        try:
            with contextlib.redirect_stdout(tee_stdout), contextlib.redirect_stderr(tee_stderr):
                product_example.main()
        except Exception:
            exit_code = 1
            traceback.print_exc(file=tee_stderr)
        finally:
            sys.argv = original_argv

    print(f"\nReport saved: {report_path}")
    if args.done:
        Path(args.done).write_text(str(exit_code), encoding="utf-8")
    input("Press Enter to close this window...")
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
