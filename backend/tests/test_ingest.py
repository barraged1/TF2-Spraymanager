"""Tests for storage isolation and SSRF-guarded ingestion."""
from __future__ import annotations

import socket

import pytest

from app.config import settings
from app.services import ingest, storage
from app.services.ingest import IngestError


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.ensure_dirs()
    yield


def test_new_job_and_dir():
    job = storage.new_job()
    assert len(job) == 32
    assert storage.job_dir(job).is_dir()


def test_job_id_validation_blocks_traversal():
    with pytest.raises(storage.StorageError):
        storage.job_dir("../etc")
    with pytest.raises(storage.StorageError):
        storage.job_dir("not-a-valid-id")


def test_job_path_sanitizes_filename():
    job = storage.new_job()
    base = storage.job_dir(job)
    # A traversal filename is neutralised to a plain name inside the job dir.
    target = storage.job_path(job, "../../escape.txt", create=True)
    assert target.parent == base.resolve()
    assert target.name == "escape.txt"


def test_save_upload_rejects_bad_extension():
    job = storage.new_job()
    with pytest.raises(IngestError):
        ingest.save_upload(job, "evil.exe", b"data")


def test_save_upload_persists_image():
    job = storage.new_job()
    path = ingest.save_upload(job, "pic.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    assert path.exists()
    assert path.suffix == ".png"


def test_save_upload_size_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 8)
    job = storage.new_job()
    with pytest.raises(IngestError):
        ingest.save_upload(job, "big.mp4", b"0" * 64)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x.mp4",
        "http://localhost/x.gif",
        "http://10.0.0.5/x.mp4",
        "http://192.168.1.10/clip.webm",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "ftp://example.com/x.mp4",
        "file:///etc/passwd",
    ],
)
def test_ssrf_guard_blocks_private_and_bad_schemes(url):
    with pytest.raises(IngestError):
        ingest._assert_public_host(url)


def test_ssrf_guard_allows_public(monkeypatch):
    # Pretend the host resolves to a public IP so we don't hit the network.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, None, None, "", ("93.184.216.34", 0))],
    )
    ingest._assert_public_host("https://example.com/video.mp4")  # should not raise


def test_import_url_disabled(monkeypatch):
    monkeypatch.setattr(settings, "url_import_enabled", False)
    job = storage.new_job()
    with pytest.raises(IngestError):
        ingest.import_url(job, "https://example.com/x.mp4")


def test_direct_media_detection_with_query_and_double_slash():
    # The reported failing URL: .jpeg with a cache-buster query and a // path.
    url = "https://wimg.rule34.xxx//images/3660/51d0375b13651ade9b1fa489dc751dae.jpeg?17564389"
    assert ingest._looks_like_direct_media(url) is True


class _FakeYDL:
    opts: dict = {}
    error = "ERROR: [twitter] 1: Video #1 is unavailable"

    def __init__(self, opts):
        type(self).opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        import yt_dlp

        raise yt_dlp.utils.DownloadError(self.error)


@pytest.fixture
def fake_ytdlp(monkeypatch):
    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    monkeypatch.setattr(ingest, "_assert_public_host", lambda url: None)
    monkeypatch.setattr(settings, "cookies_from_browser", "")
    monkeypatch.setattr(settings, "cookies_file", None)
    return _FakeYDL


def _import_error(url: str) -> str:
    with pytest.raises(IngestError) as err:
        ingest.import_url(storage.new_job(), url)
    return str(err.value)


def test_login_gated_x_post_gets_a_clean_message_with_help(fake_ytdlp):
    message = _import_error("https://x.com/someone/status/1/video/1")
    assert message.startswith("Could not import from URL: [twitter] 1: Video #1 is unavailable. ")
    assert "needs a logged-in account" in message
    assert fake_ytdlp.opts["no_color"] is True
    assert "cookiesfrombrowser" not in fake_ytdlp.opts and "cookiefile" not in fake_ytdlp.opts


def test_unrelated_failures_get_no_login_help(fake_ytdlp, monkeypatch):
    monkeypatch.setattr(_FakeYDL, "error", "ERROR: Unsupported URL: https://example.com/page")
    assert "logged-in" not in _import_error("https://example.com/page")


@pytest.mark.parametrize(
    "browser, expected",
    [("Firefox", ("firefox", None, None, None)), ("firefox:Work Profile", ("firefox", "Work Profile", None, None))],
)
def test_browser_login_is_passed_to_ytdlp(fake_ytdlp, monkeypatch, browser, expected):
    monkeypatch.setattr(settings, "cookies_from_browser", browser)
    assert "logged-in" not in _import_error("https://x.com/someone/status/1")
    assert fake_ytdlp.opts["cookiesfrombrowser"] == expected


def test_cookie_file_wins_over_browser(fake_ytdlp, monkeypatch, tmp_path):
    cookies = tmp_path / "elsewhere.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(settings, "cookies_from_browser", "chrome")
    monkeypatch.setattr(settings, "cookies_file", cookies)
    _import_error("https://x.com/someone/status/1")
    assert fake_ytdlp.opts["cookiefile"] == str(cookies)
    assert "cookiesfrombrowser" not in fake_ytdlp.opts


def test_cookies_txt_in_data_dir_is_used_automatically(fake_ytdlp):
    cookies = settings.data_dir / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    message = _import_error("https://x.com/someone/status/1")
    assert fake_ytdlp.opts["cookiefile"] == str(cookies)
    assert "may be expired" in message and "needs a logged-in account" not in message


def test_browser_cookie_failure_suggests_a_cookie_file(fake_ytdlp, monkeypatch):
    monkeypatch.setattr(settings, "cookies_from_browser", "chrome")
    monkeypatch.setattr(_FakeYDL, "error", "ERROR: Could not copy Chrome cookie database.")
    assert "export a cookies.txt" in _import_error("https://x.com/someone/status/1")


def test_direct_download_sends_browser_user_agent(tmp_path, monkeypatch):
    captured = {}

    class FakeResp:
        headers = {"content-type": "image/jpeg"}

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size=0):
            yield b"fake-image-bytes"

    class FakeStream:
        def __init__(self, *args, **kwargs):
            captured["headers"] = kwargs.get("headers", {})

        def __enter__(self):
            return FakeResp()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ingest.httpx, "stream", lambda *a, **k: FakeStream(*a, **k))

    dest = tmp_path / "out.jpeg"
    ingest._download_direct("https://wimg.example.xxx//images/x.jpeg?123", dest)

    assert dest.read_bytes() == b"fake-image-bytes"
    assert "Mozilla" in captured["headers"]["User-Agent"]
    assert captured["headers"]["Referer"].startswith("https://wimg.example.xxx")


def test_cleanup_expired(monkeypatch):
    job = storage.new_job()
    d = storage.job_dir(job)
    # Make the directory look old.
    import os

    old = 1.0
    os.utime(d, (old, old))
    removed = storage.cleanup_expired()
    assert removed >= 1
    assert not d.exists()
