"""テンプレート展開と、`<script>` に埋め込む JSON の安全性。"""

from __future__ import annotations

import json

import pytest

from sitegen.render import Template, TemplateError, escape, json_payload


def test_escape_covers_html_specials():
    assert escape('<a href="x">&\'') == "&lt;a href=&quot;x&quot;&gt;&amp;&#39;"


def test_escape_accepts_non_strings():
    assert escape(42) == "42"
    assert escape(None) == "None"


def test_json_payload_neutralises_script_close():
    """バリデータ名は運営者が自由に設定できるので `</script>` が来ても壊れてはいけない。"""
    payload = json_payload([{"n": "evil</script><img src=x onerror=alert(1)>"}])
    assert "</script>" not in payload
    assert "<" not in payload and ">" not in payload
    # エスケープしても JSON としての意味は変わらない
    assert json.loads(payload)[0]["n"] == "evil</script><img src=x onerror=alert(1)>"


def test_json_payload_escapes_line_separators():
    # U+2028 / U+2029 は JS ソース上で行終端として扱われ、そのままだと構文エラーになる
    raw = "a\u2028b\u2029c"
    payload = json_payload([raw])
    assert "\u2028" not in payload and "\u2029" not in payload
    assert "\\u2028" in payload and "\\u2029" in payload
    assert json.loads(payload)[0] == raw


def test_json_payload_keeps_non_ascii_readable():
    payload = json_payload(["南雲"])
    assert "南雲" in payload


def test_json_payload_escapes_ampersand():
    payload = json_payload(["Hodl & Hodl"])
    assert "&" not in payload
    assert json.loads(payload)[0] == "Hodl & Hodl"


@pytest.fixture
def tpl(tmp_path):
    (tmp_path / "page.html").write_text("<h1>{{ title }}</h1>{{& raw }}{{> part.html }}", encoding="utf-8")
    (tmp_path / "part.html").write_text("<p>{{ title }}</p>", encoding="utf-8")
    return Template(tmp_path)


def test_render_escapes_by_default_and_passes_raw_through(tpl):
    out = tpl.render("page.html", {"title": "<b>hi</b>", "raw": "<em>ok</em>"})
    assert "<h1>&lt;b&gt;hi&lt;/b&gt;</h1>" in out
    assert "<em>ok</em>" in out


def test_render_expands_partials_with_same_context(tpl):
    out = tpl.render("page.html", {"title": "T", "raw": ""})
    assert "<p>T</p>" in out


def test_render_rejects_unknown_token(tpl):
    with pytest.raises(TemplateError, match="未定義のトークン"):
        tpl.render("page.html", {"raw": ""})


def test_render_rejects_missing_template(tmp_path):
    with pytest.raises(TemplateError, match="template not found"):
        Template(tmp_path).render("nope.html", {})


def test_render_detects_include_cycle(tmp_path):
    (tmp_path / "loop.html").write_text("{{> loop.html }}", encoding="utf-8")
    with pytest.raises(TemplateError, match="include depth"):
        Template(tmp_path).render("loop.html", {})


def test_render_allows_dotted_and_dashed_names(tmp_path):
    (tmp_path / "a.html").write_text("{{ some-key }}|{{ other.key }}", encoding="utf-8")
    out = Template(tmp_path).render("a.html", {"some-key": "1", "other.key": "2"})
    assert out == "1|2"
