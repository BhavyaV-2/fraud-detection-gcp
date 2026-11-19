"""Load function entry points separately and keep cloud access disabled."""

import importlib.util
import os
from pathlib import Path
import sys

os.environ["GCP_PROJECT_ID"] = ""
SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC / "process_transaction"))


def _load_entry_point(name, folder):
    """Register an entry point without colliding with another main module."""
    spec = importlib.util.spec_from_file_location(name, SRC / folder / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)


_load_entry_point("ingest_main", "ingest")
_load_entry_point("worker_main", "process_transaction")
