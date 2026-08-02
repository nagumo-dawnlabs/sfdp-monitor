"""IBRL ダッシュボードの集計と色分けの仕様を固定する。

templates/assets/ibrl_criteria.js の summarize() / scoreClass() は同じアルゴリズムを
ブラウザ側で再実装しているので、ここで決めた挙動を変えるときは JS 側も必ず合わせる。
末尾の 2 つのテストは、そのしきい値が JS 側と食い違ったまま気付かない事故を防ぐ。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dashboards.ibrl_criteria import MS_TIERS, SCORE_TIERS, ms_class, score_class, summarize
from solanarpc import Node, client_label

JS = Path(__file__).resolve().parent.parent / "templates" / "assets" / "ibrl_criteria.js"


def test_average_of_a_full_history():
    t = summarize([90.0, 92.0, 94.0])
    assert t.average == pytest.approx(92.0)
    assert t.sampled == 3


def test_missing_epochs_are_excluded_from_the_denominator():
    # ブロックを作っていない epoch は 0 点ではなく「無かったこと」として扱う
    t = summarize([90.0, None, 94.0])
    assert t.average == pytest.approx(92.0)
    assert t.sampled == 2


def test_all_missing_gives_zero_not_division_error():
    t = summarize([None, None])
    assert t.average == 0.0
    assert t.sampled == 0


def test_empty_history():
    t = summarize([])
    assert (t.average, t.sampled) == (0.0, 0)


def test_zero_is_a_real_score_not_a_gap():
    # vote packing 0 のように 0 点は実際に起こる。None と混同してはいけない
    t = summarize([0.0, 100.0])
    assert t.average == pytest.approx(50.0)
    assert t.sampled == 2


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (100.0, "v-hi"),
        (95.0, "v-hi"),
        (94.99, "v-good"),
        (90.0, "v-good"),
        (89.99, "v-mid"),
        (80.0, "v-mid"),
        (79.99, "v-low"),
        (70.0, "v-low"),
        (69.99, "v-bad"),
        (0.0, "v-bad"),
    ],
)
def test_score_class_thresholds(score, expected):
    assert score_class(score) == expected


def test_js_score_tiers_match_python():
    """JS 側の SCORE_TIERS が Python と同じしきい値・同じクラス名を持つこと。"""
    source = JS.read_text(encoding="utf-8")
    block = re.search(r"const SCORE_TIERS = \[(.*?)\];", source, re.S)
    assert block, "ibrl_criteria.js に SCORE_TIERS が見つからない"
    found = [(float(n), cls) for n, cls in re.findall(r"\[(\d+(?:\.\d+)?), '([\w-]+)'\]", block.group(1))]
    assert found == [(t, c) for t, c in SCORE_TIERS]


def test_js_carries_the_same_fallback_class():
    """しきい値をすべて下回ったときのクラスも Python と揃っていること。"""
    source = JS.read_text(encoding="utf-8")
    assert "return 'v-bad';" in source
    assert score_class(0.0) == "v-bad"


# --- median slot time の色分け（低いほど良い） ------------------------------


@pytest.mark.parametrize(
    ("ms", "expected"),
    [
        (300.0, "v-hi"),
        (400.0, "v-hi"),  # IBRL が継続スロットで満点とする許容値。ここまでは緑
        (400.1, "v-good"),
        (420.0, "v-good"),
        (420.5, "v-mid"),
        (440.0, "v-mid"),
        (440.5, "v-low"),
        (470.0, "v-low"),
        (470.5, "v-bad"),
        (4290.0, "v-bad"),
    ],
)
def test_ms_class_thresholds(ms, expected):
    assert ms_class(ms) == expected


def test_ms_class_is_the_opposite_direction_from_scores():
    """スコアは高いほど良く、slot time は低いほど良い。取り違えると色が全部逆になる。"""
    assert ms_class(360.0) == "v-hi"
    assert score_class(360.0) == "v-hi"  # スコアは上限 100 なので 360 は当然「良い」
    assert ms_class(500.0) == "v-bad"
    assert score_class(50.0) == "v-bad"


def test_js_ms_tiers_match_python():
    """JS 側の MS_TIERS が Python と同じしきい値・同じクラス名を持つこと。"""
    source = JS.read_text(encoding="utf-8")
    block = re.search(r"const MS_TIERS = \[(.*?)\];", source, re.S)
    assert block, "ibrl_criteria.js に MS_TIERS が見つからない"
    found = [(float(n), cls) for n, cls in re.findall(r"\[(\d+(?:\.\d+)?), '([\w-]+)'\]", block.group(1))]
    assert found == [(t, c) for t, c in MS_TIERS]


# --- クライアント種別の判定 -------------------------------------------------

BAM_ROSTER = frozenset({"onroster"})


def _node(client_id: str, identity: str = "someone") -> Node:
    return Node(identity=identity, client_id=client_id, version="4.1.2")


@pytest.mark.parametrize(
    ("client_id", "expected"),
    [
        ("Agave", "Agave"),
        ("JitoLabs", "Jito"),
        ("Frankendancer", "Frankendancer"),
        ("Firedancer", "Firedancer"),
        ("AgavePaladin", "Paladin"),
        ("Unknown(8)", "Rakurai"),
        ("Unknown(10)", "Harmonic Agave"),
        ("Unknown(11)", "Harmonic Frankendancer"),
    ],
)
def test_client_names_are_resolved(client_id, expected):
    assert client_label(_node(client_id), BAM_ROSTER) == expected


@pytest.mark.parametrize("client_id", ["AgaveBam", "Unknown(6)"])
def test_bam_binary_counts_as_bam_only_when_on_the_roster(client_id):
    """BAM のバイナリを動かしていても、名簿に無ければ BAM とは呼ばない。"""
    assert client_label(_node(client_id, "onroster"), BAM_ROSTER) == "BAM"
    assert client_label(_node(client_id, "elsewhere"), BAM_ROSTER) == "Jito"


def test_unmapped_client_ids_are_kept_verbatim():
    """知らない番号を既知のクライアントに丸めない（誤った断定をしない）。"""
    assert client_label(_node("Unknown(99)"), BAM_ROSTER) == "Unknown(99)"


def test_missing_node_or_client_id_is_empty():
    assert client_label(None, BAM_ROSTER) == ""
    assert client_label(_node(""), BAM_ROSTER) == ""
