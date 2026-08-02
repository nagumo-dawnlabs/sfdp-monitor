"""Trillium の epoch 別バリデータ実績。

`GET /validator_rewards/<epoch>` は 1 epoch 分の全バリデータを 1 リクエストで返す
（identity pubkey 引き）。ただしレスポンスが 1 epoch で 6MB 前後あり、279 個の
フィールドのうちこのサイトが使うのは数個だけ。取り込む epoch 数を欲張らないこと。

`slot_duration_median` は ms の文字列（例 `"403.00000"`）で来る。中央値なので
偶数件のときは `.5` が出る。記録の無いバリデータは null。

内訳スコア (`build_time_score` 等) は ibrl.wtf が出しているものと同じ値がそのまま
入っている（epoch 1009 の SFDP 358 件で小数 4 桁まで全件一致を確認）。そのため
このダッシュボードは表の数字をすべて Trillium 1 か所から取っている。

最新 epoch は `GET /api/epochs` が返す配列の最大値。52 バイトで済むので、
6MB のレスポンスを epoch を知るためだけに引かなくてよい。この配列は直近 10 件しか
並ばないが、`/validator_rewards/<epoch>` 自体はもっと古い epoch も返す。
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_URL = "https://api.trillium.so"

REWARDS_PATH = "/validator_rewards/{epoch}"
EPOCHS_PATH = "/api/epochs"


@dataclass(frozen=True)
class ValidatorEpoch:
    """ある epoch における 1 バリデータの実績。"""

    identity: str
    # 主軸。スロット所要時間の中央値 (ms)
    median_ms: float
    mean_ms: float
    # Trillium 自身が「スロットが遅れている」と判定したか
    is_lagging: bool
    # IBRL の内訳スコア（ibrl.wtf と同じ値）
    slot_time: float | None
    vote_packing: float | None
    non_vote_packing: float | None
    # IBRL 総合スコア。ページには出さないがスナップショットには残す
    ibrl: float | None
    blocks_produced: int


def _number(value) -> float | None:
    """`"403.00000"` のような文字列も数値も float にする。null は None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def latest_epoch(client) -> int:
    """Trillium が持っている最新の epoch。"""
    epochs = client.get_json(EPOCHS_PATH)
    numbers = [int(e) for e in epochs if isinstance(e, int | str) and str(e).isdigit()]
    if not numbers:
        raise RuntimeError("Trillium が epoch 一覧を返さなかった")
    return max(numbers)


def fetch_epoch(client, epoch: int, *, cached: bool = True) -> dict[str, ValidatorEpoch]:
    """1 epoch 分を identity 引きの辞書で返す。中央値が無い行は落とす。"""
    path = REWARDS_PATH.format(epoch=epoch)
    payload = client.cached_json(f"trillium-e{epoch}", path) if cached else client.get_json(path)

    rows = payload if isinstance(payload, list) else (payload.get("data") or [])
    out: dict[str, ValidatorEpoch] = {}
    for row in rows:
        identity = row.get("identity_pubkey") or row.get("node_pubkey")
        median = _number(row.get("slot_duration_median"))
        if not identity or median is None:
            continue
        out[identity] = ValidatorEpoch(
            identity=identity,
            median_ms=median,
            mean_ms=_number(row.get("slot_duration_mean")) or 0.0,
            is_lagging=bool(row.get("slot_duration_is_lagging")),
            slot_time=_number(row.get("build_time_score")),
            vote_packing=_number(row.get("vote_packing_score")),
            non_vote_packing=_number(row.get("non_vote_packing_score")),
            ibrl=_number(row.get("ibrl_score")),
            blocks_produced=int(row.get("blocks_produced") or 0),
        )
    return out
