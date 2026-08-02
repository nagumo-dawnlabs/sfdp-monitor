"""Jito の BAM 関連 API のデータ取得層。

ibrl.wtf が裏で叩いている公開 API を、同じエンドポイントから読む。

- `ibrl` … explorer.bam.dev の IBRL スコア。スコア定義もここが持つ
- `roster` … kobe.mainnet.jito.network の BAM バリデータ名簿

集計や描画のロジックは持たない。HTTP・レート制御・キャッシュ・リトライは
`solanaorg.client.ApiClient` を共用する（データ源に依存しない汎用の層で、
base_url を差し替えるだけで使える）。ホストが 2 つあるので、クライアントも
`BuildEnv.make_client()` から 2 つ作って渡す。
"""

from .ibrl import (
    BASE_URL,
    WEIGHTS,
    Score,
    fetch_epoch,
    fetch_stats,
    latest_epoch,
)
from .roster import fetch_bam_identities

__all__ = [
    "BASE_URL",
    "WEIGHTS",
    "Score",
    "fetch_bam_identities",
    "fetch_epoch",
    "fetch_stats",
    "latest_epoch",
]
