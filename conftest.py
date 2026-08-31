"""
conftest.py

Корень проекта в sys.path, чтобы `python -m pytest` работал без
установки пакета. Тесты написаны на unittest — pytest подхватывает их
как есть, поэтому оба способа запуска эквивалентны:

    python -m pytest
    python -m unittest discover -s tests
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
