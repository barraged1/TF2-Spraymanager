"""Application configuration and TF2 spray constants.

Values can be overridden via environment variables (prefix ``TF2SPRAY_``) so the
tool stays flexible without code edits, but the defaults are tuned for a local,
single-user setup bound to localhost.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str) -> Optional[Path]:
    raw = os.environ.get(name, "").strip()
    return Path(raw) if raw else None


# --- TF2 spray hard limits (engine-defined) -------------------------------
#: A spray VTF must be strictly smaller than this to show up in-game.
MAX_VTF_BYTES: int = 512 * 1024
#: Animated sprays are played by the engine at a fixed framerate. The wiki and
#: the de-facto standard tool (Mishcatt VTF-Editor) use 5 FPS (0.2 s/frame).
DEFAULT_SPRAY_FPS: int = 5
#: Maximum non-power-of-two square edge for opaque (DXT1) and alpha (DXT5) sprays.
MAX_EDGE_DXT1: int = 1020
MAX_EDGE_DXT5: int = 724
#: VTF container version written (matches Mishcatt/TF2-friendly output).
VTF_VERSION: tuple[int, int] = (7, 1)


@dataclass(slots=True)
class Settings:
    """Runtime settings for the backend service."""

    host: str = field(default_factory=lambda: os.environ.get("TF2SPRAY_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("TF2SPRAY_PORT", 8790))

    #: Root for transient per-job working data (uploads, extracted frames, output).
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("TF2SPRAY_DATA_DIR", Path(__file__).resolve().parents[1] / "data")
        )
    )

    #: Maximum accepted upload size (bytes). Default 256 MiB.
    max_upload_bytes: int = field(
        default_factory=lambda: _env_int("TF2SPRAY_MAX_UPLOAD_BYTES", 256 * 1024 * 1024)
    )

    # --- URL ingest (SSRF-sensitive) ---
    #: Master switch for importing media from URLs.
    url_import_enabled: bool = field(
        default_factory=lambda: _env_bool("TF2SPRAY_URL_IMPORT", True)
    )
    #: Maximum bytes to download from a remote URL. Default 512 MiB.
    max_download_bytes: int = field(
        default_factory=lambda: _env_int("TF2SPRAY_MAX_DOWNLOAD_BYTES", 512 * 1024 * 1024)
    )
    #: Maximum seconds a download/extraction may run before being aborted.
    download_timeout_s: int = field(
        default_factory=lambda: _env_int("TF2SPRAY_DOWNLOAD_TIMEOUT", 180)
    )
    #: Browser whose logins yt-dlp may use, e.g. "firefox" or "firefox:Profile Name".
    cookies_from_browser: str = field(
        default_factory=lambda: os.environ.get("TF2SPRAY_COOKIES_FROM_BROWSER", "").strip()
    )
    #: Netscape-format cookies.txt for yt-dlp; defaults to <data_dir>/cookies.txt when that exists.
    cookies_file: Optional[Path] = field(default_factory=lambda: _env_path("TF2SPRAY_COOKIES_FILE"))

    #: How long generated job folders live before cleanup (seconds). Default 6 h.
    job_ttl_s: int = field(default_factory=lambda: _env_int("TF2SPRAY_JOB_TTL", 6 * 3600))

    #: Explicit "Team Fortress 2" folder; skips Steam auto-detection when set.
    tf2_dir_override: Optional[Path] = field(default_factory=lambda: _env_path("TF2SPRAY_TF2_DIR"))

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def library_cache_dir(self) -> Path:
        return self.data_dir / "library_cache"

    @property
    def trash_dir(self) -> Path:
        return self.data_dir / "trash"

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)


#: Allowed URL schemes for remote import.
ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})

#: Accepted upload content categories -> permitted file extensions.
ALLOWED_IMAGE_EXTS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tga"}
)
ALLOWED_VIDEO_EXTS: frozenset[str] = frozenset(
    {".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif", ".m4v"}
)

settings = Settings()
