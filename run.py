"""Launch the TF2 Spray EasyImport local web app.

Run with the project virtual environment::

    .venv\\Scripts\\python.exe run.py

Then open the printed URL (it also opens automatically). The server binds to
localhost only.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path

# Make the backend package importable.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn  # noqa: E402

from app.config import settings  # noqa: E402


def _open_browser(url: str) -> None:
    if os.environ.get("TF2SPRAY_NO_BROWSER"):
        return
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()


def main() -> None:
    url = f"http://{settings.host}:{settings.port}/"
    print("\n  TF2 Spray EasyImport")
    print(f"  -> {url}\n")
    # Show the app's own messages (e.g. rotation changes) alongside uvicorn's.
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    app_log = logging.getLogger("tf2spray")
    app_log.addHandler(handler)
    app_log.setLevel(logging.INFO)
    _open_browser(url)
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
