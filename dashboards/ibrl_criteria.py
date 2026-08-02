"""IBRL Criteria ダッシュボード。

主軸は **median slot time**（Trillium の `slot_duration_median`, ms）。SFDP
バリデータ 1 件ごとに、その epoch のスロット所要時間の中央値を遅い順に並べ、
補助として IBRL の内訳スコア（Slot Time / Vote Packing / Non-Vote Packing）と
クライアント種別を添える。IBRL の総合スコアは表には出さない。

表に出る数字は epoch も含めてすべて **Trillium 1 か所**から取る。内訳スコアは
ibrl.wtf と同じ値が Trillium にそのまま入っているため（epoch 1009 の SFDP 358 件で
小数 4 桁まで全件一致を確認）、わざわざ 2 か所から引く理由が無い。列ごとに違う
epoch や違う出所の数字が混ざることが、構造的に起きないようにしてある。

数字以外は別の源が要る:

- 名前・ロゴ・stake: api.solana.org（Trillium にも name はあるが、SFDP の
  participant state で対象を決めている以上こちらが正）
- クライアント種別: Solana の gossip + Jito の BAM 名簿

突き合わせのキーはすべて identity pubkey で、SFDP の `mainnetBetaPubkey` と同じ値。

その epoch のスロット所要時間が無いバリデータ（ブロックを作っていない等）は、
数字が出せないだけで「悪い」わけではないので、表には出さず件数だけを注記に出す。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import bam
import solanarpc
import trillium
from sitegen.logos import available_logos
from sitegen.registry import Dashboard, DashboardData
from solanaorg import sfdp
from solanaorg.client import FetchError

SLUG = "ibrl-criteria"

# 埋め込む epoch 数。平均とスパークラインに使う。
# Trillium は 1 epoch あたり 6MB 前後を返すので、ここを増やすと取得量がそのまま
# 効く（30 にすると 1 日 190MB を他所の公開 API から引くことになる）。
# 平均をならすには十分で、かつ相手に迷惑をかけない範囲としてこの値にしてある。
HISTORY = 15

# スコアの色分けのしきい値（高いほど良い）。JS 側の SCORE_TIERS と同じ値を持つ
SCORE_TIERS = ((95.0, "v-hi"), (90.0, "v-good"), (80.0, "v-mid"), (70.0, "v-low"))

# median slot time の色分け（低いほど良い）。JS 側の MS_TIERS と同じ値を持つ。
# 400ms は IBRL の方法論が「継続スロットなら満点」としている許容値で、実データも
# この前後で二山に割れる。恣意的な刻みではなくこの許容値を緑の境目にしてある。
MS_TIERS = ((400.0, "v-hi"), (420.0, "v-good"), (440.0, "v-mid"), (470.0, "v-low"))

# 「遅い」と見なす目安。KPI の件数に使う（現状 360 件中 40 件ほどが該当）
SLOW_MS = 420.0


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


def ms_class(ms: float) -> str:
    """median slot time に対応する色クラス。低いほど良いので向きが逆。

    JS 側の msClass() と同一。
    """
    for threshold, cls in MS_TIERS:
        if ms <= threshold:
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
        raise RuntimeError("データの取得には API クライアントが要る")

    # 表に出る数字はすべて Trillium 1 か所から取る。epoch も Trillium 基準なので、
    # 列ごとに違う epoch や違う出所の数字が混ざることが原理的に起きない
    tril = env.make_client(trillium.BASE_URL)
    epoch = trillium.latest_epoch(tril)
    history = max(1, min(HISTORY, env.history))
    env.log(f"Trillium: epoch {epoch} (history {history})")

    # 最新 epoch はまだ値が動くのでキャッシュしない。過去 epoch は確定値
    stats = {epoch: trillium.fetch_epoch(tril, epoch, cached=False)}
    for past in range(epoch - 1, epoch - history, -1):
        stats[past] = trillium.fetch_epoch(tril, past)
    env.log(f"Trillium: {len(stats[epoch])} validators with a slot duration at epoch {epoch}")

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

    clients = _fetch_clients(env, epoch)

    epochs_desc = [epoch - i for i in range(history)]
    # ロゴは criteria-miss 側が取り込んだものを使う（ここでは同期しない。
    # 同じディレクトリに 2 つのダッシュボードが同期すると互いのロゴを消すため）
    logos = available_logos(env.out_dir / "assets" / "logos") if env.want_assets else set()

    def _round(value, digits):
        return round(value, digits) if value is not None else None

    rows = []
    for p in profiles:
        stat = stats[epoch].get(p.pubkey)
        if stat is None:
            continue  # この epoch のスロット所要時間が無い。主軸が出せないので表に出さない
        client, version = clients.get(p.pubkey, ("", ""))
        rows.append(
            {
                "p": p.pubkey,
                "n": p.name,
                "t": p.participant_state,
                "c": client,
                "cv": version,
                "k": p.stake_sol,
                "f": p.foundation_stake_sol,
                # 主軸。slot_duration_median (ms)
                "m": round(stat.median_ms, 1),
                # IBRL の内訳スコア（ibrl.wtf と同じ値が Trillium に入っている）
                "b": _round(stat.slot_time, 2),
                "v": _round(stat.vote_packing, 2),
                "nv": _round(stat.non_vote_packing, 2),
                "bp": stat.blocks_produced,
                # Trillium 自身の「遅れている」判定。1 のときだけ持たせる
                **({"lag": 1} if stat.is_lagging else {}),
                # 表には出さないが、スナップショットとしては残す
                "i": _round(stat.ibrl, 2),
                # median slot time の履歴。新しい epoch が先頭で、その epoch に
                # 記録が無ければ null。平均・増減・スパークラインはこれから作る
                "h": [
                    round(stats[e][p.pubkey].median_ms, 1) if p.pubkey in stats.get(e, {}) else None
                    for e in epochs_desc
                ],
                # 1 のときだけ assets/logos/<pubkey>.webp が存在する
                **({"lg": 1} if p.pubkey in logos else {}),
            }
        )

    rows.sort(key=lambda r: (r["n"] or "￿").lower())
    env.log(f"{len(rows)} of {len(profiles)} SFDP validators have a slot duration this epoch")

    # 比較用のネットワーク中央値は SFDP に限らず Trillium 全件から出す
    # （表と同じ指標・同じ epoch でないと並べる意味がない）
    all_medians = sorted(s.median_ms for s in stats[epoch].values())
    network = {
        "slot_ms": round(statistics.median(all_medians), 1) if all_medians else 0.0,
        "slot_validators": len(all_medians),
        "lagging": sum(1 for s in stats[epoch].values() if s.is_lagging),
    }

    return {
        "dashboard": SLUG,
        "cluster": env.cluster,
        "participant_states": env.states,
        "epoch": epoch,
        "history": history,
        "network": network,
        # 内訳スコアの重み。IBRL の定義で、注記に出すためだけの定数
        "weights": bam.WEIGHTS,
        "slow_ms": SLOW_MS,
        "coverage": {"sfdp": len(profiles), "measured": len(rows), "unmeasured": len(profiles) - len(rows)},
        "validators": rows,
    }


def _fetch_clients(env, epoch: int) -> dict[str, tuple[str, str]]:
    """identity -> (クライアント表示名, バージョン)。

    スコアと違って補助的な列なので、ここが取れなくてもページは出す。gossip の RPC は
    公開エンドポイントで落ちることがあり、Client 列 1 つのためにダッシュボード全体を
    止めるのは割に合わない。取れなければ空にして、その旨をログに出す。
    """
    try:
        nodes = solanarpc.fetch_cluster_nodes(env.make_client(env.rpc_url))
        bam_ids = bam.fetch_bam_identities(env.make_client(bam.roster.BASE_URL), epoch)
    except (FetchError, RuntimeError, OSError, KeyError, TypeError, ValueError) as exc:
        env.log(f"warning: クライアント情報を取得できなかった。Client 列は空になる: {exc}")
        return {}

    labelled = {pk: (solanarpc.client_label(n, bam_ids), n.version) for pk, n in nodes.items()}
    named = sum(1 for name, _ in labelled.values() if name)
    env.log(f"clients: {len(nodes)} gossip nodes, {named} identified, {len(bam_ids)} on the BAM roster")
    return labelled


def _context(snapshot: dict) -> dict:
    cov = snapshot["coverage"]
    validators = snapshot["validators"]
    net = snapshot["network"]
    return {
        "epoch": snapshot["epoch"],
        "history": snapshot["history"],
        "cluster": snapshot["cluster"],
        "participant_states": snapshot["participant_states"],
        "measured": f"{cov['measured']:,}",
        "unmeasured": f"{cov['unmeasured']:,}",
        "sfdp_total": f"{cov['sfdp']:,}",
        "network_ms": _ms(net.get("slot_ms", 0.0)),
        "network_validators": f"{net.get('slot_validators', 0):,}",
        "lagging": f"{sum(1 for v in validators if v.get('lag')):,}",
        "slow_ms": _ms(SLOW_MS),
        # 鮮度バッジに出す「何をどこまで見ているか」の 1 行
        "coverage": f"Epoch {snapshot['epoch']} · {cov['measured']:,} of {cov['sfdp']:,} SFDP validators measured",
        # lede から ibrl.wtf の実ページへ 1 件リンクして出典を辿れるようにする
        "sample_pubkey": validators[0]["p"] if validators else "",
    }


def _ms(value: float) -> str:
    """`403.0` -> `403`、`420.5` -> `420.5`。中央値なので .5 が出る。"""
    return f"{value:.1f}".removesuffix(".0")


def _stats(snapshot: dict) -> list[tuple[str, str]]:
    rows = snapshot["validators"]
    if not rows:
        return [("0", "validators measured")]
    times = sorted(r["m"] for r in rows)
    slow = sum(1 for ms in times if ms > SLOW_MS)
    return [
        (f"{len(rows):,}", "validators measured"),
        (f"{_ms(statistics.median(times))} ms", "median slot time"),
        (f"{slow:,}", f"slower than {_ms(SLOW_MS)} ms"),
    ]


DASHBOARD = Dashboard(
    slug=SLUG,
    title="IBRL Criteria",
    tagline="Median slot time of every Solana Foundation Delegation Program validator, slowest first.",
    description=(
        "Median slot time of every Solana Foundation Delegation Program validator, "
        "with the IBRL slot time and packing component scores alongside it."
    ),
    template="ibrl_criteria.html",
    footer_template="ibrl_criteria_footer.html",
    scripts=("table.js", "ibrl_criteria.js"),
    collect=collect,
)
