"""Vercel serverless entrypoint: exposes the FastAPI app for /api/* routes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backend.app import app  # noqa: E402,F401
