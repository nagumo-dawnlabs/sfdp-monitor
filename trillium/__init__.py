"""api.trillium.so のデータ取得層。

ibrl-criteria ダッシュボードが表に出す数字はすべてここから来る。主軸は
`slot_duration_median`（スロット所要時間の中央値, ms）で、IBRL の内訳スコアも
同じ値が入っているため 1 か所に寄せてある。

HTTP・レート制御・キャッシュ・リトライは `solanaorg.client.ApiClient` を共用する。
"""

from .rewards import (
    BASE_URL,
    ValidatorEpoch,
    fetch_epoch,
    latest_epoch,
)

__all__ = [
    "BASE_URL",
    "ValidatorEpoch",
    "fetch_epoch",
    "latest_epoch",
]
