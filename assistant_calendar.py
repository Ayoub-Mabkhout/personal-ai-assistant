"""Compatibility entry point for the assistant's local calendar."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from personal_assistant.calendar import Calendar, DEFAULT_DB, instant, main


if __name__ == '__main__':
    sys.exit(main())
