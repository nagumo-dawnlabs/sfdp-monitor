"""IBRL ダッシュボードの集計と色分けの仕様を固定する。

templates/assets/ibrl_criteria.js の summarize() / scoreClass() は同じアルゴリズムを
ブラウザ側で再実装しているので、ここで決めた挙動を変えるときは JS 側も必ず合わせる。
末尾の 2 つのテストは、そのしきい値が JS 側と食い違ったまま気付かない事故を防ぐ。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dashboards.ibrl_criteria import SCORE_TIERS, score_class, summarize

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
