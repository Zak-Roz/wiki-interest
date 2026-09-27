#!/usr/bin/env python3
"""Entry point. Run `python scripts/wiki.py --help`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wikiinterest.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
