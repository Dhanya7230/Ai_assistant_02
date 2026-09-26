"""
Vercel looks for a FastAPI/ASGI app export at one of a fixed set of paths
(see the Vercel Python/FastAPI docs). This file just re-exports the real
app defined in backend/main.py so the project structure doesn't have to
change to satisfy that convention.
"""
from backend.main import app  # noqa: F401
