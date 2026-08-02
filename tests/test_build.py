"""fixture からサイト全体をビルドし、生成物が壊れていないことを確かめる。

テンプレートを実ファイルに分離したので、トークンの取りこぼしや壊れた HTML は
ここで拾える。API は一切叩かない。

ダッシュボードを増やしたら `FIXTURES` に fixture を足すこと。足し忘れると
そのダッシュボードだけ API を叩きにいき、テストがネットワークに依存する。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import build as build_cli

REPO = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO / "tests" / "fixtures"

# slug -> fixture。build.py は snapshot の "dashboard" フィールドで対象を判別する
FIXTURES = {
    "criteria-miss": FIXTURE_DIR / "criteria-miss.json",
    "ibrl-criteria": FIXTURE_DIR / "ibrl-criteria.json",
}
SLUGS = sorted(FIXTURES)


@pytest.fixture
def site(tmp_path):
    args = ["--out", str(tmp_path), "--history", "64", "--templates", str(REPO / "templates")]
    for path in FIXTURES.values():
        args += ["--fixture", str(path)]
    assert build_cli.main(args) == 0
    return tmp_path


def test_every_registered_dashboard_has_a_fixture():
    """新しいダッシュボードを fixture 無しで登録すると、テストが API を叩いてしまう。"""
    from dashboards import DASHBOARDS

    assert sorted(d.slug for d in DASHBOARDS) == SLUGS


def test_expected_files_exist(site):
    for rel in (
        ".nojekyll",
        "index.html",
        "assets/theme.css",
        "assets/table.js",
        "assets/criteria_miss.js",
        "assets/ibrl_criteria.js",
        "assets/logo-dawnlabs.png",
    ):
        assert (site / rel).is_file(), rel
    for slug in SLUGS:
        assert (site / slug / "index.html").is_file(), slug
        assert (site / "data" / f"{slug}.json").is_file(), slug


def test_no_unreplaced_tokens(site):
    for page in site.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        assert "{{" not in text, f"{page.name} にトークンが残っている"


@pytest.mark.parametrize("slug", SLUGS)
def test_pages_reference_versioned_assets(site, slug):
    page = (site / slug / "index.html").read_text(encoding="utf-8")
    assert "../assets/theme.css?v=" in page
    assert "../assets/table.js?v=" in page
    # ロゴは data URI ではなく実ファイル参照（同一ページに 2 回埋め込む無駄をなくした）
    assert "data:image/png;base64" not in page


def test_hub_links_to_every_dashboard(site):
    hub = (site / "index.html").read_text(encoding="utf-8")
    for slug in SLUGS:
        assert f'href="{slug}/"' in hub
    assert "SFDP Criteria Miss Rate" in hub
    assert "IBRL Criteria" in hub


@pytest.mark.parametrize("slug", SLUGS)
def test_dashboard_links_back_to_hub(site, slug):
    assert 'class="breadcrumb"' in (site / slug / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("slug", SLUGS)
def test_freshness_badge_carries_a_machine_readable_timestamp(site, slug):
    page = (site / slug / "index.html").read_text(encoding="utf-8")
    assert 'class="freshness"' in page
    # JS 無効でも読める絶対時刻 + JS が相対時間を出すための ISO 属性
    m = re.search(r'<time datetime="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)">([^<]+)</time>', page)
    assert m, "freshness バッジに ISO タイムスタンプが無い"
    assert m.group(2).endswith("UTC"), "公開ページなのでローカル時刻ではなく UTC で出す"


def test_freshness_badge_states_what_is_covered(site):
    # 何をどこまで見ているかもバッジに出す
    assert "Epochs 944–1007" in (site / "criteria-miss" / "index.html").read_text(encoding="utf-8")
    assert "Epoch 1009" in (site / "ibrl-criteria" / "index.html").read_text(encoding="utf-8")


def test_hub_has_no_freshness_badge(site):
    assert 'class="freshness"' not in (site / "index.html").read_text(encoding="utf-8")


def _embedded_data(page: str):
    start = page.index("const DATA = ") + len("const DATA = ")
    return json.loads(page[start : page.index(";</script>", start)])


@pytest.mark.parametrize("slug", SLUGS)
def test_embedded_data_matches_snapshot_on_disk(site, slug):
    on_disk = json.loads((site / "data" / f"{slug}.json").read_text(encoding="utf-8"))
    embedded = _embedded_data((site / slug / "index.html").read_text(encoding="utf-8"))
    assert embedded == on_disk
    assert embedded == json.loads(FIXTURES[slug].read_text(encoding="utf-8"))


@pytest.mark.parametrize("slug", SLUGS)
def test_script_tag_is_not_broken_by_validator_names(site, slug):
    """どの fixture にも `</script>` を名前に含むレコードを入れてある。"""
    page = (site / slug / "index.html").read_text(encoding="utf-8")
    after_data = page[page.index("const DATA = ") :]
    # DATA ブロックを閉じる `;</script>` より前に </script> が現れてはいけない。
    # 現れていればバリデータ名が script を早期終了させている
    assert after_data.index("</script>") == after_data.index(";</script>") + 1
    # 開始タグと終了タグの数が合っていること
    assert page.count("<script") == page.count("</script>")


@pytest.mark.parametrize("slug", SLUGS)
def test_fixture_contains_a_script_injection_record(slug):
    """注入テストが素通りしていないこと（fixture 側の担保）。"""
    raw = FIXTURES[slug].read_text(encoding="utf-8")
    assert "</script>" in raw, f"{slug} の fixture に注入レコードが無い"


def test_skip_unchanged_is_a_noop_on_second_run(site, tmp_path):
    before = {p: p.read_bytes() for p in site.rglob("*") if p.is_file()}
    args = ["--out", str(site), "--history", "64", "--templates", str(REPO / "templates"), "--skip-unchanged"]
    for path in FIXTURES.values():
        args += ["--fixture", str(path)]
    assert build_cli.main(args) == 0
    after = {p: p.read_bytes() for p in site.rglob("*") if p.is_file()}
    assert before == after


def test_unknown_slug_is_an_error(tmp_path):
    assert build_cli.main(["--only", "nope", "--out", str(tmp_path)]) == 2


def test_partial_build_does_not_drop_other_cards_from_the_hub(site):
    """--only でハブを作り直すと、ビルドしなかったカードが消えてしまう。

    ハブは「今回ビルドしたダッシュボード」だけを並べて組み立てるので、部分ビルドの
    ときは据え置くのが正しい。
    """
    before = (site / "index.html").read_text(encoding="utf-8")
    assert 'href="criteria-miss/"' in before

    rc = build_cli.main(
        [
            "--only",
            "ibrl-criteria",
            "--fixture",
            str(FIXTURES["ibrl-criteria"]),
            "--out",
            str(site),
            "--history",
            "64",
            "--templates",
            str(REPO / "templates"),
        ]
    )
    assert rc == 0
    after = (site / "index.html").read_text(encoding="utf-8")
    assert after == before, "部分ビルドがハブを書き換えている"
    assert 'href="criteria-miss/"' in after
