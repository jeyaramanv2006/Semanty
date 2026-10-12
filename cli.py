"""
Root CLI entry point for Semanty.
Allows running the CLI directly from the Semanty root directory:
  python cli.py index <path>
  python cli.py search "<query>"
  python cli.py interactive
  python cli.py stats
  python cli.py evaluate
"""
import os
import sys
from pathlib import Path

# Ensure the Semanty root directory is in sys.path so 'cli' package resolves
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cli.cli_app import main

if __name__ == "__main__":
    main()
