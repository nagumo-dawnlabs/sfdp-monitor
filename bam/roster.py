"""BAM バリデータの名簿 (Jito Kobe API)。

gossip 上で BAM のバイナリを名乗っているノードが、実際に BAM バリデータとして
登録されているかを判定するためだけに使う。`solanarpc.client_label()` の引数になる。

名簿には `is_eligible` が false の行も含まれるが、絞り込まずに全 identity を採る
（ibrl.wtf も同じ扱いで、「登録されているか」と「報酬対象か」は別の話のため）。
"""

from __future__ import annotations

BASE_URL = "https://kobe.mainnet.jito.network"

VALIDATORS_PATH = "/api/v1/bam_validators"


def fetch_bam_identities(client, epoch: int) -> frozenset[str]:
    """その epoch に BAM 名簿へ載っている identity pubkey の集合。"""
    payload = client.get_json(VALIDATORS_PATH, epoch=str(epoch))
    rows = payload.get("bam_validators") or []
    return frozenset(r["identity_account"] for r in rows if r.get("identity_account"))
