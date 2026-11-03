"""Media ingestion: validated uploads and SSRF-guarded URL imports.

Two ingest paths are supported:

* **Uploads** — bytes posted from the browser, validated by extension and size.
* **URLs** — direct media links are streamed with ``httpx``; everything else is
  handed to ``yt-dlp`` (YouTube/social). Both validate that the target host does
  not resolve to a private/loopback address before connecting.

URL importing can be disabled entirely via configuration. Because ``yt-dlp`` and
redirects may reach CDNs we do not pre-resolve, this guard is best-effort and the
server is intended to be bound to localhost for personal use.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import (
    ALLOWED_IMAGE_EXTS,
    ALLOWED_URL_SCHEMES,
    ALLOWED_VIDEO_EXTS,
    settings,
)
from . import storage

_ALL_EXTS = ALLOWED_IMAGE_EXTS | ALLOWED_VIDEO_EXTS

#: Many image/video hosts (booru CDNs, etc.) reject the default library
#: User-Agent with 403/400. Present a normal browser identity instead.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "image/avif,image/webp,image/apng,image/*,video/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_LOGIN_WORDS = re.compile(r"log ?in|sign ?in|authenticat|cookies|nsfw|age.restricted", re.IGNORECASE)
_LOGIN_HELP = (
    "This post probably needs a logged-in account (X hides age-restricted media from "
    "logged-out visitors). Export your cookies.txt and save it as backend\\data\\cookies.txt "
    "(see the README), or download the video yourself and drop the file in."
)
_BROWSER_COOKIE_HELP = (
    "Chrome and Edge often block cookie access on Windows; export a cookies.txt "
    "file instead (see the README)."
)
_EXPIRED_LOGIN_HELP = (
    "Your saved login may be expired or for a different account; log into X again "
    "(and re-export cookies.txt if you use one)."
)


class IngestError(Exception):
    """A user-facing ingestion problem (bad type, too large, blocked host)."""


def _ext_of(name: str) -> str:
    return Path(name).suffix.lower()


def validate_upload_name(filename: str) -> str:
    ext = _ext_of(filename)
    if ext not in _ALL_EXTS:
        raise IngestError(
            f"Unsupported file type '{ext or '?'}'. "
            "Allowed: images (png/jpg/gif/webp/bmp/tga) and video (mp4/webm/mov/...)."
        )
    return ext


def save_upload(job_id: str, filename: str, data: bytes) -> Path:
    """Validate and persist uploaded bytes into the job directory."""
    validate_upload_name(filename)
    if len(data) > settings.max_upload_bytes:
        raise IngestError("Upload exceeds the maximum allowed size.")
    if not data:
        raise IngestError("Uploaded file is empty.")
    dest = storage.job_path(job_id, f"source{_ext_of(filename)}", create=True)
    dest.write_bytes(data)
    return dest


def _assert_public_host(url: str) -> None:
    """Block non-http(s) schemes and hosts that resolve to private ranges."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise IngestError("Only http and https URLs are allowed.")
    host = parsed.hostname
    if not host:
        raise IngestError("URL has no host.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise IngestError(f"Could not resolve host '{host}'.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise IngestError(f"Refusing to fetch from non-public address ({ip}).")


def _looks_like_direct_media(url: str) -> bool:
    return _ext_of(urlparse(url).path) in _ALL_EXTS


def _download_direct(url: str, dest: Path) -> Path:
    cap = settings.max_download_bytes
    timeout = httpx.Timeout(settings.download_timeout_s)
    parsed = urlparse(url)
    # A matching Referer helps with hotlink-protected hosts.
    headers = {**_BROWSER_HEADERS, "Referer": f"{parsed.scheme}://{parsed.hostname}/"}
    total = 0
    with httpx.stream(
        "GET", url, follow_redirects=True, timeout=timeout, headers=headers
    ) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1 << 16):
                total += len(chunk)
                if total > cap:
                    raise IngestError("Remote file exceeds the maximum download size.")
                fh.write(chunk)
    if total == 0:
        raise IngestError("Remote file was empty.")
    return dest


def _ytdlp_login_opts() -> dict:
    cookie_file = settings.cookies_file or settings.data_dir / "cookies.txt"
    if cookie_file.is_file():
        return {"cookiefile": str(cookie_file)}
    if settings.cookies_from_browser:
        browser, _, profile = settings.cookies_from_browser.partition(":")
        return {"cookiesfrombrowser": (browser.strip().lower(), profile.strip() or None, None, None)}
    return {}


def _is_x_post(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith(f".{d}") for d in ("x.com", "twitter.com"))


def _describe_ytdlp_error(url: str, exc: Exception) -> str:
    message = str(exc).strip().removeprefix("ERROR:").strip().rstrip(".")
    text = f"Could not import from URL: {message}."
    login = _ytdlp_login_opts()
    if "cookiesfrombrowser" in login and "cookie" in message.lower():
        return f"{text} {_BROWSER_COOKIE_HELP}"
    # X answers logged-out requests for age-restricted posts with "no video" instead of a login error.
    x_gated = _is_x_post(url) and ("unavailable" in message or "No video could be found" in message)
    if x_gated or _LOGIN_WORDS.search(message):
        return f"{text} {_EXPIRED_LOGIN_HELP if login else _LOGIN_HELP}"
    return text


def _download_ytdlp(url: str, out_dir: Path) -> Path:
    import yt_dlp  # heavy; import lazily

    template = str(out_dir / "source.%(ext)s")
    opts = {
        "outtmpl": template,
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "max_filesize": settings.max_download_bytes,
        "socket_timeout": settings.download_timeout_s,
        "quiet": True,
        "no_warnings": True,
        "no_color": True,
        "restrictfilenames": True,
        "http_headers": {"User-Agent": _BROWSER_UA},
        **_ytdlp_login_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)

    candidates = sorted(out_dir.glob("source.*"))
    if not candidates:
        raise IngestError("Downloader did not produce a media file (link unsupported?).")
    return candidates[0]


def import_url(job_id: str, url: str) -> Path:
    """Fetch ``url`` into the job directory and return the saved file path."""
    if not settings.url_import_enabled:
        raise IngestError("URL import is disabled on this server.")
    url = url.strip()
    _assert_public_host(url)

    out_dir = storage.job_dir(job_id, create=True)
    if _looks_like_direct_media(url):
        ext = _ext_of(urlparse(url).path)
        try:
            return _download_direct(url, out_dir / f"source{ext}")
        except httpx.HTTPError as exc:
            raise IngestError(f"Download failed: {exc}") from exc
    try:
        return _download_ytdlp(url, out_dir)
    except IngestError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the UI
        raise IngestError(_describe_ytdlp_error(url, exc)) from exc
