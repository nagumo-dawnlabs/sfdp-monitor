"""explorer.bam.dev のデータ取得層。

ibrl.wtf が裏で叩いている公開 API を、同じエンドポイントから読む。
`ibrl` が IBRL スコアのエンドポイントとスコア定義を担い、集計や描画は持たない。

HTTP・レート制御・キャッシュ・リトライは `solanaorg.client.ApiClient` を共用する
（データ源に依存しない汎用の層で、base_url を差し替えるだけで使える）。
"""

from .ibrl import (
    BASE_URL,
    WEIGHTS,
    Score,
    fetch_epoch,
    fetch_stats,
    latest_epoch,
)

__all__ = [
    "BASE_URL",
    "WEIGHTS",
    "Score",
    "fetch_epoch",
    "fetch_stats",
    "latest_epoch",
]
