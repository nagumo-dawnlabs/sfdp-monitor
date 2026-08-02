"""api.solana.org のデータ取得層。

`client` が HTTP・レート制御・キャッシュ・リトライを、`sfdp` が SFDP 固有の
エンドポイントと state 定義を担う。集計や描画のロジックは持たない。
"""

from .client import ApiClient, FetchError
from .sfdp import (
    CODE,
    MISSING,
    STATE_ICON,
    ValidatorStates,
    collect_profiles,
    collect_states,
    fetch_participants,
    latest_epoch,
)

__all__ = [
    "CODE",
    "MISSING",
    "STATE_ICON",
    "ApiClient",
    "FetchError",
    "ValidatorStates",
    "collect_profiles",
    "collect_states",
    "fetch_participants",
    "latest_epoch",
]
