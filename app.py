"""Vercel entrypoint.

Vercel's Python runtime looks for a FastAPI instance named ``app`` at a
supported root entrypoint (``app.py``, ``index.py``, ``server.py``, ``main.py``,
``wsgi.py``, ``asgi.py``). The real application lives in ``backend/main.py``;
this file only re-exports it. Running the app locally is unchanged —
``uvicorn backend.main:app``.
"""
from backend.main import app

__all__ = ['app']
