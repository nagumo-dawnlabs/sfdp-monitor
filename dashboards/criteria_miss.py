"""SFDP 基準未達率ダッシュボード。

直近 `history` epoch 分の state を 1 文字コードの列として持ち、集計期間の切り替えは
ブラウザ側で行う。Python 側の `aggregate()` は CLI レポートと、この文字列表現が
正しいことを検証するテストのために存在する。
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from sitegen.logos import sync_logos
from sitegen.registry import Dashboard, DashboardData
from solanaorg import sfdp

SLUG = "criteria-miss"

# ハブのカードに出す KPI を計算する窓。ダッシュボードの初期表示と揃えてある
HUB_WINDOW = 64


@dataclass(frozen=True)
class Counts:
    """ある窓における 1 バリデータの内訳。"""

    bonus: int = 0
    baseline: int = 0
    none: int = 0
    party: int = 0
    missing: int = 0
    evaluated: int = 0
    streak: int = 0

    @property
    def miss_rate(self) -> float:
        return 100.0 * self.none / self.evaluated if self.evaluated else 0.0

    @property
    def not_bonus_rate(self) -> float:
        return 100.0 * (self.none + self.baseline) / self.evaluated if self.evaluated else 0.0


def aggregate(states: str, window: int) -> Counts:
    """新しい epoch を先頭とした state 列を、直近 `window` 分だけ集計する。

    templates/assets/criteria_miss.js の aggregate() と同一アルゴリズム。
    片方を変えたら必ずもう片方も変えること。

    - データ無し (`-`) は分母 (`evaluated`) から外す
    - `streak` は最新 epoch から連続する `N` の数。データ無しは連続を途切れさせない
      （記録が無いだけで「達成した」わけではないため）
    """
    window = max(0, window)
    s = states[:window]
    tally = {sfdp.MISSING: 0, "B": 0, "L": 0, "N": 0, "H": 0}
    streak = 0
    streak_open = True
    for c in s:
        tally[c] = tally.get(c, 0) + 1
        if c == "N" and streak_open:
            streak += 1
        elif c != sfdp.MISSING:
            streak_open = False
    missing = tally[sfdp.MISSING]
    return Counts(
        bonus=tally["B"],
        baseline=tally["L"],
        none=tally["N"],
        party=tally["H"],
        missing=missing,
        evaluated=len(s) - missing,
        streak=streak,
    )


def miss_epochs(states: str, window: int, end_epoch: int) -> list[int]:
    """未達だった epoch 番号を新しい順に返す。state 列の先頭が `end_epoch` に対応する。"""
    return [end_epoch - i for i, c in enumerate(states[:window]) if c == "N"]


# --- 収集 ------------------------------------------------------------------


def collect(env) -> DashboardData:
    snapshot = env.fixtures.get(SLUG)
    if snapshot is not None:
        env.log(f"fixture: {len(snapshot['validators'])} validators, epoch {snapshot['window']['end']}")
    else:
        snapshot = _fetch_snapshot(env)
    return DashboardData(snapshot=snapshot, context=_context(snapshot), stats=_stats(snapshot))


def _fetch_snapshot(env) -> dict:
    client = env.client
    participants = sfdp.fetch_participants(client, env.state_set or None)
    env.log(f"{len(participants)} participants")

    end = sfdp.latest_epoch(client, participants, env.cluster)
    env.log(f"window: epoch {end - env.history + 1}-{end} ({env.cluster})")

    rows, failed = sfdp.collect_states(
        client,
        participants,
        env.cluster,
        end,
        env.history,
        concurrency=env.concurrency,
        log=env.log,
    )

    # 429 で一部が欠けたページを公開してしまわないよう、ここで止める
    if rows and failed:
        missing_pct = 100.0 * len(failed) / (len(rows) + len(failed))
        env.log(f"warning: {len(failed)} validators failed to fetch ({missing_pct:.1f}%)")
        if missing_pct > env.max_missing_pct:
            raise RuntimeError(
                f"取得失敗が {missing_pct:.1f}% で上限 {env.max_missing_pct}% を超えた。"
                f"劣化したページを公開しないため中止する (例: {failed[:3]})"
            )
    if not rows:
        raise RuntimeError("no validator data collected")

    rows.sort(key=lambda r: (r.name or "￿").lower())

    # ロゴは外部ホスト配信なので、ビルド時に取り込んで自サイトから出す
    with_logo: set[str] = set()
    if env.want_assets:
        with_logo = sync_logos(
            env.out_dir / "assets" / "logos",
            {r.pubkey: r.image_url for r in rows if r.image_url},
            log=env.log,
        )

    return {
        "dashboard": SLUG,
        "cluster": env.cluster,
        "participant_states": env.states,
        "window": {"start": end - env.history + 1, "end": end, "history": env.history},
        "state_codes": {code: state for state, code in sfdp.CODE.items()},
        "missing_code": sfdp.MISSING,
        "validators": [
            {
                "p": r.pubkey,
                "n": r.name,
                "t": r.participant_state,
                "k": r.stake_sol,
                "f": r.foundation_stake_sol,
                "s": r.states,
                # 1 のときだけ assets/logos/<pubkey>.webp が存在する
                **({"i": 1} if r.pubkey in with_logo else {}),
            }
            for r in rows
        ],
    }


def _context(snapshot: dict) -> dict:
    w = snapshot["window"]
    validators = snapshot["validators"]
    return {
        "start_epoch": w["start"],
        "end_epoch": w["end"],
        "history": w["history"],
        "cluster": snapshot["cluster"],
        "participant_states": snapshot["participant_states"],
        # 鮮度バッジに出す「何をどこまで見ているか」の 1 行
        "coverage": f"Epochs {w['start']}–{w['end']} · {len(validators):,} validators",
        # lede から solana.org の実ページへ 1 件リンクして出典を辿れるようにする
        "sample_pubkey": validators[0]["p"] if validators else "",
    }


def _stats(snapshot: dict) -> list[tuple[str, str]]:
    window = min(HUB_WINDOW, snapshot["window"]["history"])
    min_eval = max(1, -(-window // 2))
    counts = [aggregate(v["s"], window) for v in snapshot["validators"]]
    pool = [c for c in counts if c.evaluated >= min_eval]
    total_none = sum(c.none for c in pool)
    total_eval = sum(c.evaluated for c in pool)
    rate = 100.0 * total_none / total_eval if total_eval else 0.0
    return [
        (f"{len(pool):,}", "validators"),
        (f"{sum(1 for c in pool if c.none):,}", f"missed ≥ 1 of last {window}"),
        (f"{rate:.2f}%", "aggregate miss rate"),
    ]


DASHBOARD = Dashboard(
    slug=SLUG,
    title="SFDP Criteria Miss Rate",
    tagline="How often each Solana Foundation Delegation Program validator failed to meet program criteria, epoch by epoch.",
    description=(
        "How often each Solana Foundation Delegation Program validator failed to meet program criteria, epoch by epoch."
    ),
    template="criteria_miss.html",
    footer_template="criteria_miss_footer.html",
    scripts=("table.js", "criteria_miss.js"),
    collect=collect,
)


# --- CLI レポート出力 -------------------------------------------------------

CSV_HEADER = [
    "rank",
    "name",
    "pubkey",
    "participant_state",
    "miss_rate_pct",
    "missed",
    "rated",
    "no_data",
    "not_bonus_rate_pct",
    "current_streak",
    "bonus",
    "baseline",
    "none",
    "none_high_third_party_stake",
    "activated_stake_sol",
    "sfdp_stake_sol",
    "window_start_epoch",
    "window_end_epoch",
]


@dataclass
class ReportRow:
    validator: dict
    counts: Counts

    @property
    def name(self) -> str:
        return self.validator["n"] or "(no name)"


def report_rows(snapshot: dict, window: int, min_evaluated: int, min_rate: float) -> list[ReportRow]:
    """スナップショットから、指定窓のランキング行を作る。

    ダッシュボードのブラウザ側と同じ `aggregate()` を通すので、両者の数字は一致する。
    """
    rows = [ReportRow(v, aggregate(v["s"], window)) for v in snapshot["validators"]]
    rows = [r for r in rows if r.counts.evaluated >= min_evaluated]
    rows.sort(key=lambda r: (-r.counts.miss_rate, -r.counts.none, r.name.lower()))
    return [r for r in rows if r.counts.miss_rate >= min_rate]


def write_csv(path: Path, rows: list[ReportRow], start: int, end: int) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for i, r in enumerate(rows, 1):
            c = r.counts
            w.writerow(
                [
                    i,
                    r.validator["n"],
                    r.validator["p"],
                    r.validator["t"],
                    f"{c.miss_rate:.2f}",
                    c.none,
                    c.evaluated,
                    c.missing,
                    f"{c.not_bonus_rate:.2f}",
                    c.streak,
                    c.bonus,
                    c.baseline,
                    c.none,
                    c.party,
                    r.validator["k"],
                    r.validator["f"],
                    start,
                    end,
                ]
            )


def write_markdown(
    path: Path, rows: list[ReportRow], pool: list[ReportRow], start: int, end: int, cluster: str, top: int
) -> None:
    flagged = [r for r in pool if r.counts.none]
    pct = 100 * len(flagged) / len(pool) if pool else 0.0
    lines = [
        f"# SFDP 基準未達率 ({cluster})",
        "",
        f"- 対象 epoch: `{start}` – `{end}` ({end - start + 1} epochs)",
        f"- 集計バリデータ: {len(pool)} 件",
        f"- 未達 (赤バツ) が 1 epoch 以上あるバリデータ: {len(flagged)} 件 ({pct:.1f}%)",
        f"- 本表に掲載: {len(rows)} 件",
        "",
        "未達率 = `None` (赤バツ) の epoch 数 / データのある epoch 数。",
        "`Baseline` (オレンジのチェック) は matching 未達だが residual は達成のため未達には数えていない",
        "（参考として not_bonus 率に含む）。",
        "",
        f"## 未達率ランキング (上位 {top} 件)",
        "",
        "| # | Name | 未達率 | 未達/評価 | not_bonus率 | 連続未達 | Pubkey |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows[:top], 1):
        c = r.counts
        lines.append(
            f"| {i} | {r.name} | {c.miss_rate:.1f}% | {c.none}/{c.evaluated} "
            f"| {c.not_bonus_rate:.1f}% | {c.streak or '-'} | `{r.validator['p']}` |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_json(path: Path, rows: list[ReportRow], start: int, end: int, cluster: str) -> None:
    path.write_text(
        json.dumps(
            {
                "cluster": cluster,
                "window": {"start": start, "end": end, "epochs": end - start + 1},
                "state_icon_map": sfdp.STATE_ICON,
                "validators": [
                    {
                        "pubkey": r.validator["p"],
                        "name": r.validator["n"],
                        "state": r.validator["t"],
                        "miss_rate_pct": round(r.counts.miss_rate, 2),
                        "not_bonus_rate_pct": round(r.counts.not_bonus_rate, 2),
                        "missed": r.counts.none,
                        "evaluated": r.counts.evaluated,
                        "missing": r.counts.missing,
                        "streak": r.counts.streak,
                        "counts": {
                            "Bonus": r.counts.bonus,
                            "Baseline": r.counts.baseline,
                            "None": r.counts.none,
                            "NoneHighThirdPartyStake": r.counts.party,
                        },
                        "activated_stake_sol": r.validator["k"],
                        "sfdp_stake_sol": r.validator["f"],
                        "miss_epochs": miss_epochs(r.validator["s"], end - start + 1, end),
                    }
                    for r in rows
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
