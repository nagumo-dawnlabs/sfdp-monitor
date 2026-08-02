"""api.trillium.so のデータ取得層。

このサイトが使うのは `slot_duration_median`（epoch ごと・バリデータごとの
スロット所要時間の中央値, ms）だけ。IBRL 側の `median_block_build_ms` とは
測り方が違う別の指標で、こちらを主軸に据えている。

HTTP・レート制御・キャッシュ・リトライは `solanaorg.client.ApiClient` を共用する。
"""

from .rewards import (
    BASE_URL,
    SlotDuration,
    fetch_epoch,
)

__all__ = [
    "BASE_URL",
    "SlotDuration",
    "fetch_epoch",
]
