"""Trillium の epoch 別バリデータ実績から、スロット所要時間の中央値を取る。

`GET /validator_rewards/<epoch>` は 1 epoch 分の全バリデータを 1 リクエストで返す
（identity pubkey 引き）。ただしレスポンスが 1 epoch で 6MB 前後あり、279 個の
フィールドのうちこのサイトが使うのは数個だけ。取り込む epoch 数を欲張らないこと。

`slot_duration_median` は ms の文字列（例 `"403.00000"`）で来る。中央値なので
偶数件のときは `.5` が出る。ブロックを作っていない epoch などでは null。
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_URL = "https://api.trillium.so"

REWARDS_PATH = "/validator_rewards/{epoch}"


@dataclass(frozen=True)
class SlotDuration:
    """ある epoch における 1 バリデータのスロット所要時間 (ms)。"""

    identity: str
    median: float
    mean: float
    # Trillium 自身が「遅れている」と判定したか。参考値として持っておく
    is_lagging: bool


def _number(value) -> float | None:
    """`"403.00000"` のような文字列も数値も float にする。null は None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_epoch(client, epoch: int, *, cached: bool = True) -> dict[str, SlotDuration]:
    """1 epoch 分を identity 引きの辞書で返す。中央値が無い行は落とす。"""
    path = REWARDS_PATH.format(epoch=epoch)
    payload = client.cached_json(f"trillium-e{epoch}", path) if cached else client.get_json(path)

    rows = payload if isinstance(payload, list) else (payload.get("data") or [])
    out: dict[str, SlotDuration] = {}
    for row in rows:
        identity = row.get("identity_pubkey") or row.get("node_pubkey")
        median = _number(row.get("slot_duration_median"))
        if not identity or median is None:
            continue
        out[identity] = SlotDuration(
            identity=identity,
            median=median,
            mean=_number(row.get("slot_duration_mean")) or 0.0,
            is_lagging=bool(row.get("slot_duration_is_lagging")),
        )
    return out
