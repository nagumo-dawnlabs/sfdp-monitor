"""IBRL Criteria ダッシュボード。

SFDP バリデータ 1 件ごとに、現在 epoch の IBRL スコア（と内訳の Slot Time /
Vote Packing / Non-Vote Packing、Median Block Build）を並べる。

データ源が 2 つあるのがこのダッシュボードの特徴:

- スコアそのもの: explorer.bam.dev（ibrl.wtf の裏の API）。identity pubkey 引き
- 名前・ロゴ・stake: api.solana.org。IBRL 側は pubkey しか返さないため

突き合わせのキーは identity pubkey で、SFDP の `mainnetBetaPubkey` と同じ値。

ブロックを 1 つも作っていない epoch のバリデータは IBRL 側に行が無い。数字が
出せないだけで「悪い」わけではないので、表には出さず件数だけを注記に出す。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import bam
from sitegen.logos import available_logos
from sitegen.registry import Dashboard, DashboardData
from solanaorg import sfdp

SLUG = "ibrl-criteria"

# 埋め込む epoch 数。スパークラインと平均に使うだけなので短くてよい
# （1 epoch = 1 リクエストなので取得は軽いが、ページの重さは行数 x これで効く）
HISTORY = 30

# スコアの色分けのしきい値（高いほど良い）。JS 側の SCORE_TIERS と同じ値を持つ
SCORE_TIERS = ((95.0, "v-hi"), (90.0, "v-good"), (80.0, "v-mid"), (70.0, "v-low"))


@dataclass(frozen=True)
class Trend:
    """1 バリデータの IBRL スコア履歴の要約。"""

    average: float
    sampled: int  # 平均に使えた epoch 数（データの無い epoch は数えない）


def summarize(history: list[float | None]) -> Trend:
    """新しい epoch を先頭とした IBRL スコア列を平均する。

    templates/assets/ibrl_criteria.js の summarize() と同一アルゴリズム。
    片方を変えたら必ずもう片方も変えること
    （tests/test_ibrl.py が Python 側を固定している）。

    データの無い epoch (`None`) は分母から外す。1 件も無ければ平均は 0。
    """
    seen = [v for v in history if v is not None]
    return Trend(average=statistics.fmean(seen) if seen else 0.0, sampled=len(seen))


def score_class(score: float) -> str:
    """スコアに対応する色クラス。JS 側の scoreClass() と同一。"""
    for threshold, cls in SCORE_TIERS:
        if score >= threshold:
            return cls
    return "v-bad"


# --- 収集 ------------------------------------------------------------------


def collect(env) -> DashboardData:
    snapshot = env.fixtures.get(SLUG)
    if snapshot is not None:
        env.log(f"fixture: {len(snapshot['validators'])} validators, epoch {snapshot['epoch']}")
    else:
        snapshot = _fetch_snapshot(env)
    return DashboardData(snapshot=snapshot, context=_context(snapshot), stats=_stats(snapshot))


def _fetch_snapshot(env) -> dict:
    if env.make_client is None:
        raise RuntimeError("IBRL データの取得には API クライアントが要る")
    ibrl = env.make_client(bam.BASE_URL)

    network = bam.fetch_stats(ibrl)
    epoch = bam.latest_epoch(ibrl, network["epoch"])
    history = max(1, min(HISTORY, env.history))
    env.log(f"IBRL: epoch {epoch} (history {history}), network score {network['ibrl_score']:.2f}")

    # 最新 epoch はまだ値が動くのでキャッシュしない。過去 epoch は確定値
    scores = {epoch: bam.fetch_epoch(ibrl, epoch, cached=False)}
    for past in range(epoch - 1, epoch - history, -1):
        scores[past] = bam.fetch_epoch(ibrl, past)
    env.log(f"IBRL: {len(scores[epoch])} validators scored at epoch {epoch}")

    # 名前・ロゴ・stake は SFDP 側から。ディスクキャッシュ越しなので、同じビルドで
    # criteria-miss が先に走っていれば追加の API 呼び出しはほぼ発生しない
    participants = sfdp.fetch_participants(env.client, env.state_set or None)
    env.log(f"{len(participants)} SFDP participants")
    profiles, failed = sfdp.collect_profiles(
        env.client, participants, env.cluster, concurrency=env.concurrency, log=env.log
    )

    if profiles and failed:
        missing_pct = 100.0 * len(failed) / (len(profiles) + len(failed))
        env.log(f"warning: {len(failed)} validators failed to fetch ({missing_pct:.1f}%)")
        if missing_pct > env.max_missing_pct:
            raise RuntimeError(
                f"取得失敗が {missing_pct:.1f}% で上限 {env.max_missing_pct}% を超えた。"
                f"劣化したページを公開しないため中止する (例: {failed[:3]})"
            )
    if not profiles:
        raise RuntimeError("no validator profiles collected")

    epochs_desc = [epoch - i for i in range(history)]
    current = scores[epoch]
    # ロゴは criteria-miss 側が取り込んだものを使う（ここでは同期しない。
    # 同じディレクトリに 2 つのダッシュボードが同期すると互いのロゴを消すため）
    logos = available_logos(env.out_dir / "assets" / "logos") if env.want_assets else set()

    rows = []
    for p in profiles:
        score = current.get(p.pubkey)
        if score is None:
            continue  # この epoch にブロックを作っていない。数字が出せないので表には出さない
        rows.append(
            {
                "p": p.pubkey,
                "n": p.name,
                "t": p.participant_state,
                "k": p.stake_sol,
                "f": p.foundation_stake_sol,
                "i": round(score.ibrl, 2),
                "b": round(score.slot_time, 2),
                "v": round(score.vote_packing, 2),
                "nv": round(score.non_vote_packing, 2),
                "m": score.median_block_ms,
                "bp": score.blocks_produced,
                "tr": round(score.trend, 2),
                # 新しい epoch が先頭。その epoch にデータが無ければ null
                "h": [
                    round(scores[e][p.pubkey].ibrl, 1) if p.pubkey in scores.get(e, {}) else None for e in epochs_desc
                ],
                # 1 のときだけ assets/logos/<pubkey>.webp が存在する
                **({"lg": 1} if p.pubkey in logos else {}),
            }
        )

    rows.sort(key=lambda r: (r["n"] or "￿").lower())
    env.log(f"IBRL: {len(rows)} of {len(profiles)} SFDP validators have a score this epoch")

    return {
        "dashboard": SLUG,
        "cluster": env.cluster,
        "participant_states": env.states,
        "epoch": epoch,
        "history": history,
        "network": network,
        "weights": bam.WEIGHTS,
        "coverage": {"sfdp": len(profiles), "scored": len(rows), "unscored": len(profiles) - len(rows)},
        "validators": rows,
    }


def _context(snapshot: dict) -> dict:
    cov = snapshot["coverage"]
    validators = snapshot["validators"]
    net = snapshot["network"]
    return {
        "epoch": snapshot["epoch"],
        "history": snapshot["history"],
        "cluster": snapshot["cluster"],
        "participant_states": snapshot["participant_states"],
        "scored": f"{cov['scored']:,}",
        "unscored": f"{cov['unscored']:,}",
        "sfdp_total": f"{cov['sfdp']:,}",
        "network_score": f"{net['ibrl_score']:.2f}",
        "network_validators": f"{net['active_validators']:,}",
        # 鮮度バッジに出す「何をどこまで見ているか」の 1 行
        "coverage": f"Epoch {snapshot['epoch']} · {cov['scored']:,} of {cov['sfdp']:,} SFDP validators scored",
        # lede から ibrl.wtf の実ページへ 1 件リンクして出典を辿れるようにする
        "sample_pubkey": validators[0]["p"] if validators else "",
    }


def _stats(snapshot: dict) -> list[tuple[str, str]]:
    rows = snapshot["validators"]
    if not rows:
        return [("0", "validators scored")]
    scores = sorted(r["i"] for r in rows)
    below = sum(1 for s in scores if s < 85.0)
    return [
        (f"{len(rows):,}", "validators scored"),
        (f"{statistics.median(scores):.1f}", "median IBRL score"),
        (f"{below:,}", "scoring below 85"),
    ]


DASHBOARD = Dashboard(
    slug=SLUG,
    title="IBRL Criteria",
    tagline="IBRL score and its slot time / packing components for every Solana Foundation Delegation Program validator.",
    description=(
        "IBRL score and its slot time / packing components for every Solana Foundation Delegation Program validator."
    ),
    template="ibrl_criteria.html",
    footer_template="ibrl_criteria_footer.html",
    scripts=("table.js", "ibrl_criteria.js"),
    collect=collect,
)
