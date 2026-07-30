"""ロゴ同期のマニフェスト運用。ネットワークは使わない。

日次ジョブでの差分をロゴが変わった分だけに抑えるのがこの仕組みの目的なので、
「URL が同じなら再取得しない」「参加者から外れたら消える」を固定しておく。
"""

from __future__ import annotations

import json
from typing import ClassVar

from sitegen import logos


def _seed(dest, entries: dict[str, str]) -> None:
    """取り込み済みの状態を作る。"""
    dest.mkdir(parents=True, exist_ok=True)
    for pk in entries:
        (dest / f"{pk}.webp").write_bytes(b"fake-webp")
    (dest / logos.MANIFEST_NAME).write_text(json.dumps(entries), encoding="utf-8")


def test_unchanged_urls_are_reused_without_fetching(tmp_path, monkeypatch):
    dest = tmp_path / "logos"
    _seed(dest, {"AAA": "https://example.test/a.png"})

    def boom(url):
        raise AssertionError(f"再取得してはいけない: {url}")

    monkeypatch.setattr(logos, "_fetch", boom)

    assert logos.sync_logos(dest, {"AAA": "https://example.test/a.png"}) == {"AAA"}
    assert (dest / "AAA.webp").is_file()


def test_changed_url_is_refetched(tmp_path, monkeypatch):
    dest = tmp_path / "logos"
    _seed(dest, {"AAA": "https://example.test/old.png"})
    calls = []
    monkeypatch.setattr(logos, "_fetch", lambda url: calls.append(url) or b"raw")
    monkeypatch.setattr(logos, "_shrink", lambda body, size: b"shrunk")
    monkeypatch.setattr(logos, "_pillow_available", lambda: True)

    assert logos.sync_logos(dest, {"AAA": "https://example.test/new.png"}) == {"AAA"}
    assert calls == ["https://example.test/new.png"]
    assert (dest / "AAA.webp").read_bytes() == b"shrunk"
    assert json.loads((dest / logos.MANIFEST_NAME).read_text())["AAA"].endswith("new.png")


def test_missing_file_is_refetched_even_if_manifest_matches(tmp_path, monkeypatch):
    dest = tmp_path / "logos"
    _seed(dest, {"AAA": "https://example.test/a.png"})
    (dest / "AAA.webp").unlink()
    monkeypatch.setattr(logos, "_fetch", lambda url: b"raw")
    monkeypatch.setattr(logos, "_shrink", lambda body, size: b"shrunk")
    monkeypatch.setattr(logos, "_pillow_available", lambda: True)

    assert logos.sync_logos(dest, {"AAA": "https://example.test/a.png"}) == {"AAA"}
    assert (dest / "AAA.webp").is_file()


def test_departed_validators_are_pruned(tmp_path, monkeypatch):
    dest = tmp_path / "logos"
    _seed(dest, {"AAA": "https://example.test/a.png", "BBB": "https://example.test/b.png"})
    monkeypatch.setattr(logos, "_fetch", lambda url: b"raw")

    assert logos.sync_logos(dest, {"AAA": "https://example.test/a.png"}) == {"AAA"}
    assert not (dest / "BBB.webp").exists()
    assert list(json.loads((dest / logos.MANIFEST_NAME).read_text())) == ["AAA"]


def test_fetch_failure_falls_back_to_no_logo(tmp_path, monkeypatch):
    dest = tmp_path / "logos"
    monkeypatch.setattr(logos, "_pillow_available", lambda: True)

    def fetch(url):
        raise OSError("boom")

    monkeypatch.setattr(logos, "_fetch", fetch)
    assert logos.sync_logos(dest, {"AAA": "https://example.test/a.png"}) == set()
    assert not (dest / "AAA.webp").exists()


def test_without_pillow_existing_logos_survive(tmp_path, monkeypatch):
    """依存が入っていないだけでページからロゴが一斉に消える、という壊れ方をしない。"""
    dest = tmp_path / "logos"
    _seed(dest, {"AAA": "https://example.test/a.png"})
    monkeypatch.setattr(logos, "_pillow_available", lambda: False)
    monkeypatch.setattr(logos, "_fetch", lambda url: (_ for _ in ()).throw(AssertionError("fetch すべきでない")))

    # AAA は URL が同じなので維持され、新規の BBB だけ諦める
    assert logos.sync_logos(dest, {"AAA": "https://example.test/a.png", "BBB": "https://example.test/b.png"}) == {"AAA"}
    assert (dest / "AAA.webp").is_file()


class _FakeResp:
    """Content-Length を申告しない巨大レスポンス。"""

    headers: ClassVar[dict[str, str]] = {}

    def read(self, n):
        return b"x" * n

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_oversized_source_is_rejected(tmp_path, monkeypatch):
    """壊れた URL や巨大画像でリポジトリを膨らませない。"""
    dest = tmp_path / "logos"
    monkeypatch.setattr(logos, "_pillow_available", lambda: True)
    monkeypatch.setattr(logos, "MAX_SOURCE_BYTES", 16)
    monkeypatch.setattr(logos, "_shrink", lambda body, size: b"shrunk")
    monkeypatch.setattr(logos.urllib.request, "urlopen", lambda *a, **k: _FakeResp())

    assert logos.sync_logos(dest, {"AAA": "https://example.test/big.png"}) == set()
    assert not (dest / "AAA.webp").exists()
