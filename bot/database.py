"""
Modular re-export of canonical database layer.
Guarantees a single SQLAlchemy engine, declarative Base, and SessionLocal pool across all modules.
"""
import sys
from pathlib import Path

root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import database

# Re-export all canonical database attributes
for attr in dir(database):
    if not attr.startswith("__"):
        globals()[attr] = getattr(database, attr)

__all__ = [attr for attr in dir(database) if not attr.startswith("__")]
