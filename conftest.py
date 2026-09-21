"""
conftest.py — project-root pytest configuration.

Ensures the project root directory is at the front of sys.path so that
``parsers``, ``core``, ``config``, and ``schemas`` packages resolve without
an install step.  This file is always loaded by pytest before any test module
is imported.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
