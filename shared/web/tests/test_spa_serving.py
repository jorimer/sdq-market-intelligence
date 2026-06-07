"""Regression tests for SPA static serving (cache headers + BrowserRouter fallback).

These guard the production behaviour fixed when users reported "the old UI": a
cached index.html points at stale hashed bundles. The fix forces revalidation on
HTML while caching hashed assets forever, and serves index.html for client-side
routes so deep links don't 404.

Self-contained: builds a throwaway dist on a temp dir instead of relying on a
real `frontend/dist` build (which isn't present in the backend CI job).
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import SPAStaticFiles


def _client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>SDQ</title>")
    (dist / "assets" / "index-ABC123.js").write_text("console.log('app')")
    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="frontend")
    return TestClient(app)


def test_index_is_never_cached(tmp_path):
    c = _client(tmp_path)
    for path in ("/", "/index.html"):
        r = c.get(path)
        assert r.status_code == 200
        assert "no-cache" in r.headers["cache-control"]
        assert r.headers["content-type"].startswith("text/html")


def test_hashed_assets_are_cached_immutably(tmp_path):
    c = _client(tmp_path)
    r = c.get("/assets/index-ABC123.js")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]
    assert "max-age=31536000" in r.headers["cache-control"]


def test_client_routes_fall_back_to_index(tmp_path):
    c = _client(tmp_path)
    for path in ("/banking-score", "/macro-monitor/some/deep/route"):
        r = c.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        # Served as the SPA shell, which must stay revalidated.
        assert "no-cache" in r.headers["cache-control"]


def test_missing_assets_still_404(tmp_path):
    c = _client(tmp_path)
    r = c.get("/assets/does-not-exist.js")
    assert r.status_code == 404
