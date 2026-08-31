"""
scripts/count_tests.py

Считает тесты и, при --update-readme, вписывает актуальное число в README.

Существует потому, что в README было захардкожено «132 tests — all pass»,
и цифра разошлась с действительностью. Число, которое нельзя проверить
командой, врать будет всегда.

    python scripts/count_tests.py
    python scripts/count_tests.py --update-readme
"""
from __future__ import annotations
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MARKER_START = "<!-- TEST_COUNT_START -->"
MARKER_END = "<!-- TEST_COUNT_END -->"


def count() -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    total = 0
    stack = [suite]
    while stack:
        item = stack.pop()
        if isinstance(item, unittest.TestSuite):
            stack.extend(list(item))
        else:
            total += 1
    return total


def main():
    n = count()
    print(f"Тестов обнаружено: {n}")
    if "--update-readme" in sys.argv:
        readme = ROOT / "README.md"
        text = readme.read_text(encoding="utf-8")
        block = f"{MARKER_START}\n**{n} automated tests.** Run `python -m pytest` or `python -m unittest discover -s tests`.\n{MARKER_END}"
        if MARKER_START in text:
            text = re.sub(f"{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}", block, text, flags=re.S)
        else:
            text = block + "\n\n" + text
        readme.write_text(text, encoding="utf-8")
        print(f"README обновлён: {n}")


if __name__ == "__main__":
    main()
