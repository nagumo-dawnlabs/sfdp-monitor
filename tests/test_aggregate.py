"""集計ロジックの仕様を固定する。

templates/assets/criteria_miss.js の aggregate() は同じアルゴリズムをブラウザ側で
再実装しているので、ここで決めた挙動を変えるときは JS 側も必ず合わせる。
"""

from __future__ import annotations

import pytest

from dashboards.criteria_miss import aggregate, miss_epochs, report_rows


def test_all_bonus():
    c = aggregate("BBBB", 4)
    assert (c.bonus, c.none, c.evaluated, c.missing) == (4, 0, 4, 0)
    assert c.miss_rate == 0.0
    assert c.not_bonus_rate == 0.0
    assert c.streak == 0


def test_mixed_states_and_rates():
    # 新しい epoch が先頭。N=2, L=1, B=1 -> evaluated 4
    c = aggregate("NNLB", 4)
    assert (c.none, c.baseline, c.bonus, c.evaluated) == (2, 1, 1, 4)
    assert c.miss_rate == 50.0
    # not_bonus は None + Baseline
    assert c.not_bonus_rate == 75.0


def test_baseline_is_not_a_miss():
    c = aggregate("LLLL", 4)
    assert c.miss_rate == 0.0
    assert c.not_bonus_rate == 100.0


def test_party_popper_counts_as_met():
    c = aggregate("HHNN", 4)
    assert c.party == 2
    assert c.miss_rate == 50.0
    assert c.not_bonus_rate == 50.0


def test_missing_excluded_from_denominator():
    c = aggregate("N---", 4)
    assert (c.missing, c.evaluated, c.none) == (3, 1, 1)
    assert c.miss_rate == 100.0


def test_all_missing_gives_zero_rate_not_division_error():
    c = aggregate("----", 4)
    assert c.evaluated == 0
    assert c.miss_rate == 0.0
    assert c.not_bonus_rate == 0.0


def test_streak_counts_from_newest():
    assert aggregate("NNNB", 4).streak == 3
    assert aggregate("BNNN", 4).streak == 0


def test_missing_does_not_break_a_streak():
    # 記録が無いだけで「達成した」わけではないので連続は途切れない
    assert aggregate("-NN", 3).streak == 2
    assert aggregate("N-N", 3).streak == 2
    # 一方 Bonus / Baseline は連続を切る
    assert aggregate("N-BN", 4).streak == 1
    assert aggregate("NLN", 3).streak == 1


def test_window_shorter_than_history():
    states = "NNNNBBBB"
    assert aggregate(states, 4).none == 4
    assert aggregate(states, 8).none == 4
    assert aggregate(states, 4).evaluated == 4


def test_window_longer_than_history_uses_available_data_only():
    # 分母は「要求した窓」ではなく「実際にある epoch 数」で決まる
    c = aggregate("NB", 64)
    assert c.evaluated == 2
    assert c.miss_rate == 50.0


def test_zero_and_negative_window():
    for w in (0, -5):
        c = aggregate("NNNN", w)
        assert c.evaluated == 0
        assert c.miss_rate == 0.0


def test_miss_epochs_are_newest_first_and_absolute():
    assert miss_epochs("NBN", 3, 1000) == [1000, 998]
    assert miss_epochs("NBN", 1, 1000) == [1000]


def _snapshot(validators):
    return {
        "dashboard": "criteria-miss",
        "cluster": "mainnet-beta",
        "participant_states": "Approved",
        "window": {"start": 937, "end": 1000, "history": 64},
        "validators": validators,
    }


def test_report_rows_sorts_and_filters():
    snap = _snapshot(
        [
            {"p": "a", "n": "Alpha", "t": "Approved", "k": 1, "f": 0, "s": "NNBB"},  # 50%
            {"p": "b", "n": "Bravo", "t": "Approved", "k": 1, "f": 0, "s": "NNNB"},  # 75%
            {"p": "c", "n": "Cold", "t": "Approved", "k": 1, "f": 0, "s": "BBBB"},  # 0%
            {"p": "d", "n": "New", "t": "Approved", "k": 1, "f": 0, "s": "N---"},  # 分母1で除外させる
        ]
    )
    rows = report_rows(snap, 4, min_evaluated=2, min_rate=0.0)
    assert [r.validator["p"] for r in rows] == ["b", "a", "c"]  # 未達率の降順

    only_high = report_rows(snap, 4, min_evaluated=2, min_rate=60.0)
    assert [r.validator["p"] for r in only_high] == ["b"]

    with_new = report_rows(snap, 4, min_evaluated=1, min_rate=0.0)
    assert "d" in [r.validator["p"] for r in with_new]


def test_report_row_name_falls_back():
    snap = _snapshot([{"p": "x", "n": "", "t": "Approved", "k": 0, "f": 0, "s": "BB"}])
    assert report_rows(snap, 2, 1, 0.0)[0].name == "(no name)"


@pytest.mark.parametrize(
    ("states", "window", "expected_rate"),
    [
        ("N", 1, 100.0),
        ("B", 1, 0.0),
        ("NB", 2, 50.0),
        ("NNB", 3, pytest.approx(66.67, abs=0.01)),
    ],
)
def test_rate_arithmetic(states, window, expected_rate):
    assert aggregate(states, window).miss_rate == expected_rate
