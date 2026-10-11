"""Central place for settings. Everything can be overridden with environment variables."""

import os
from pathlib import Path

# Project root (the folder that contains "app/").
BASE_DIR = Path(__file__).resolve().parent.parent

# SQLite database file. Override with e.g. DATABASE_URL=sqlite:///./other.db
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'certificates.db'}")

# Folder where generated PDFs are stored. Tests replace this with a temp folder.
CERTIFICATE_DIR = Path(os.getenv("CERTIFICATE_DIR", BASE_DIR / "generated_certificates"))

# Maximum number of recipients accepted in ONE request (documented in the README).
MAX_BATCH_SIZE = 500
