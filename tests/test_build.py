"""fixture からサイト全体をビルドし、生成物が壊れていないことを確かめる。

テンプレートを実ファイルに分離したので、トークンの取りこぼしや壊れた HTML は
ここで拾える。API は一切叩かない。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import build as build_cli

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "criteria-miss.json"


@pytest.fixture
def site(tmp_path):
    rc = build_cli.main(
        ["--fixture", str(FIXTURE), "--out", str(tmp_path), "--history", "64", "--templates", str(REPO / "templates")]
    )
    assert rc == 0
    return tmp_path


def test_expected_files_exist(site):
    for rel in (
        ".nojekyll",
        "index.html",
        "criteria-miss/index.html",
        "data/criteria-miss.json",
        "assets/theme.css",
        "assets/table.js",
        "assets/criteria_miss.js",
        "assets/logo-dawnlabs.png",
    ):
        assert (site / rel).is_file(), rel


def test_no_unreplaced_tokens(site):
    for page in site.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert "{{" not in text, f"{page.name} にトークンが残っている"


def test_pages_reference_versioned_assets(site):
    page = (site / "criteria-miss" / "index.html").read_text(encoding="utf-8")
    assert "../assets/theme.css?v=" in page
    assert "../assets/table.js?v=" in page
    assert "../assets/criteria_miss.js?v=" in page
    # ロゴは data URI ではなく実ファイル参照（同一ページに 2 回埋め込む無駄をなくした）
    assert "data:image/png;base64" not in page


def test_hub_links_to_dashboard(site):
    hub = (site / "index.html").read_text(encoding="utf-8")
    assert 'href="criteria-miss/"' in hub
    assert "SFDP Criteria Miss Rate" in hub


def test_dashboard_links_back_to_hub(site):
    page = (site / "criteria-miss" / "index.html").read_text(encoding="utf-8")
    assert 'class="breadcrumb"' in page


def test_freshness_badge_carries_a_machine_readable_timestamp(site):
    page = (site / "criteria-miss" / "index.html").read_text(encoding="utf-8")
    assert 'class="freshness"' in page
    # JS 無効でも読める絶対時刻 + JS が相対時間を出すための ISO 属性
    m = re.search(r'<time datetime="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)">([^<]+)</time>', page)
    assert m, "freshness バッジに ISO タイムスタンプが無い"
    assert m.group(2).endswith("UTC"), "公開ページなのでローカル時刻ではなく UTC で出す"
    # 何をどこまで見ているかもバッジに出す
    assert "Epochs 944–1007" in page


def test_hub_has_no_freshness_badge(site):
    assert 'class="freshness"' not in (site / "index.html").read_text(encoding="utf-8")


def test_embedded_data_matches_snapshot_on_disk(site):
    on_disk = json.loads((site / "data" / "criteria-miss.json").read_text(encoding="utf-8"))
    page = (site / "criteria-miss" / "index.html").read_text(encoding="utf-8")
    start = page.index("const DATA = ") + len("const DATA = ")
    embedded = json.loads(page[start : page.index(";</script>", start)])
    assert embedded == on_disk
    assert embedded == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_script_tag_is_not_broken_by_validator_names(site):
    """fixture には `</script>` を名前に含むレコードを入れてある。"""
    page = (site / "criteria-miss" / "index.html").read_text(encoding="utf-8")
    after_data = page[page.index("const DATA = ") :]
    # DATA ブロックを閉じる `;</script>` より前に </script> が現れてはいけない。
    # 現れていればバリデータ名が script を早期終了させている
    assert after_data.index("</script>") == after_data.index(";</script>") + 1
    # 開始タグと終了タグの数が合っていること
    assert page.count("<script") == page.count("</script>")


def test_skip_unchanged_is_a_noop_on_second_run(site, tmp_path):
    before = {p: p.read_bytes() for p in site.rglob("*") if p.is_file()}
    rc = build_cli.main(
        [
            "--fixture",
            str(FIXTURE),
            "--out",
            str(site),
            "--history",
            "64",
            "--templates",
            str(REPO / "templates"),
            "--skip-unchanged",
        ]
    )
    assert rc == 0
    after = {p: p.read_bytes() for p in site.rglob("*") if p.is_file()}
    assert before == after


def test_unknown_slug_is_an_error(tmp_path):
    assert build_cli.main(["--only", "nope", "--out", str(tmp_path)]) == 2
