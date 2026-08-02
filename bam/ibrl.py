"""IBRL スコアのエンドポイントとスコア定義。

ibrl.wtf のバリデータページに出ている数値は、この API がそのまま返している値。
`build_time_score` が UI 上の «Slot Time Score»、`median_block_build_ms` が
«Median Block Build (ms)» に対応する（実ページと突き合わせて確認済み）。

IBRL スコアの定義（ibrl.wtf/methodology）:

    IBRL = 0.40 x Slot Time + 0.15 x Vote Packing + 0.45 x Non-Vote Packing

取得は「1 epoch あたり 1 リクエスト」の一括エンドポイントなので、SFDP 側のような
バリデータ単位の部分失敗が起きない。取り切れなければ例外がそのまま上がってビルドが
止まる（劣化したページを公開しないため）。

`client` は `solanaorg.client.ApiClient` と同じインターフェース
（`get_json` / `cached_json`）を持つオブジェクト。
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_URL = "https://explorer.bam.dev"

STATS_PATH = "/api/v1/ibrl_stats"
VALIDATORS_PATH = "/api/v1/ibrl_validators"

# 各スコアの重み（ページの注記に出す。合計は 1.0）
WEIGHTS = {
    "slot_time": 0.40,
    "vote_packing": 0.15,
    "non_vote_packing": 0.45,
}


@dataclass(frozen=True)
class Score:
    """ある epoch における 1 バリデータの IBRL スコア一式。

    `identity` は Solana の identity pubkey で、SFDP 側の `mainnetBetaPubkey` と
    同じ値。ダッシュボードはこれを突き合わせのキーにしている。
    """

    identity: str
    ibrl: float
    slot_time: float  # API 上は build_time_score
    vote_packing: float
    non_vote_packing: float
    median_block_ms: int
    blocks_produced: int
    # 直前 epoch からの IBRL スコアの変化量（API が計算済みの値）
    trend: float


def _score(row: dict) -> Score:
    return Score(
        identity=row["identity"],
        ibrl=float(row.get("ibrl_score") or 0.0),
        slot_time=float(row.get("build_time_score") or 0.0),
        vote_packing=float(row.get("vote_packing_score") or 0.0),
        non_vote_packing=float(row.get("non_vote_packing_score") or 0.0),
        median_block_ms=int(row.get("median_block_build_ms") or 0),
        blocks_produced=int(row.get("blocks_produced") or 0),
        trend=float(row.get("epoch_trend") or 0.0),
    )


def fetch_stats(client) -> dict:
    """ネットワーク全体の平均スコアと、API が「現在」としている epoch。

    epoch が変わった直後は最新 epoch にまだ 1 件もデータが無いことがあるため、
    ここで得た epoch は `latest_epoch()` で必ず裏を取ってから使う。
    """
    payload = client.get_json(STATS_PATH)
    data = payload.get("data") or {}
    return {
        "epoch": int(payload.get("epoch") or 0),
        "ibrl_score": float(data.get("network_ibrl_score") or 0.0),
        "slot_time": float(data.get("avg_build_time_score") or 0.0),
        "vote_packing": float(data.get("avg_vote_packing_score") or 0.0),
        "non_vote_packing": float(data.get("avg_non_vote_packing_score") or 0.0),
        "median_block_ms": int(data.get("median_block_build_ms") or 0),
        "active_validators": int(data.get("active_validators") or 0),
    }


def fetch_epoch(client, epoch: int | None = None, *, cached: bool = True) -> dict[str, Score]:
    """1 epoch 分の全バリデータのスコアを identity 引きの辞書で返す。

    `epoch` を省略すると API が「現在」としている epoch を返す。集計途中の最新
    epoch は値が動くので、呼び出し側は最新 epoch だけ `cached=False` で取る。
    """
    query = {"epoch": str(epoch)} if epoch is not None else {}
    if cached and epoch is not None:
        payload = client.cached_json(f"ibrl-e{epoch}", VALIDATORS_PATH, **query)
    else:
        payload = client.get_json(VALIDATORS_PATH, **query)
    return {row["identity"]: _score(row) for row in (payload.get("data") or []) if row.get("identity")}


def latest_epoch(client, hint: int) -> int:
    """データが実際に入っている最新の epoch を返す。

    epoch が切り替わった直後は新 epoch の行数が 0 になるため、1 つ前まで遡る。
    """
    for epoch in (hint, hint - 1):
        if epoch > 0 and fetch_epoch(client, epoch, cached=False):
            return epoch
    raise RuntimeError(f"IBRL データのある epoch が見つからない (hint={hint})")
