#!/usr/bin/env python3
"""SFDP (Solana Foundation Delegation Program) の epoch 別基準達成状況を集計する。

solana.org の各バリデータページ (Mainnet Beta セクション) に出ている
epoch ごとのアイコンは、API の `mnStats.epochs[epoch]` の state 値と 1:1 で対応する。

    Bonus                     -> 緑の星        (matching 基準を満たした)
    Baseline                  -> オレンジのチェック (matching は未達、residual のみ達成)
    None                      -> 赤いバツ      (基準未達)
    NoneHighThirdPartyStake   -> 緑のクラッカー (third party stake が十分で SFDP stake 不要)

本スクリプトは直近 N epoch について「赤いバツ (= None) の割合」を算出し、
CSV / Markdown / JSON でリスト化する。

使い方:
    python3 sfdp_status.py --epochs 10
    python3 sfdp_status.py --epochs 30 --cluster testnet --min-rate 10
    python3 sfdp_status.py --epochs 10 --states Approved,TestnetOnboarded
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

API = "https://api.solana.org"
PARTICIPANTS_URL = f"{API}/api/community/v1/sfdp_participants"
VALIDATOR_URL = f"{API}/api/validators/{{pk}}"
EPOCH_STATS_URL = f"{API}/api/validators/epoch-stats"

# state 値 -> solana.org UI 上のアイコン
STATE_ICON = {
    "Bonus": "green-star",
    "Baseline": "orange-check",
    "None": "red-x",
    "NoneHighThirdPartyStake": "green-party-popper",
}

# 赤いバツ = 基準未達 とみなす state
UNMET_STATES = {"None"}
# 「緑の星ではない」= matching 基準未達 とみなす state
NOT_BONUS_STATES = {"None", "Baseline"}

USER_AGENT = "sfdp-monitor/1.0 (+https://github.com/DawnLabsTech)"

CACHE_DIR = Path(".cache")
CACHE_TTL = 3600.0


class RateLimiter:
    """api.solana.org は 429 を返すので全スレッド共有のトークンバケットで抑える。"""

    def __init__(self, rps: float):
        self._interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        if not self._interval:
            return
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if wait:
            time.sleep(wait)


LIMITER = RateLimiter(4.0)


def fetch_json(url: str, retries: int = 6, timeout: int = 30):
    last: Exception | None = None
    for attempt in range(retries):
        LIMITER.acquire()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            last = exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            exc.close()
            if exc.code == 429:
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0 * (attempt + 1)
                time.sleep(delay)
                continue
            if 400 <= exc.code < 500 and exc.code != 429:
                break
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


USE_CACHE = True


def fetch_validator(pk: str):
    """バリデータ詳細を取得する。epochs は全履歴を含むのでディスクにキャッシュする。"""
    use_cache = USE_CACHE
    path = CACHE_DIR / f"{pk}.json"
    if use_cache and path.exists() and (time.time() - path.stat().st_mtime) < CACHE_TTL:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    data = fetch_json(VALIDATOR_URL.format(pk=pk) + "?cacheStatus=enable")
    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    return data


@dataclass
class Row:
    pubkey: str
    name: str
    state: str
    onboarding_epoch: int | None
    counts: dict[str, int] = field(default_factory=dict)
    missing: int = 0
    evaluated: int = 0
    unmet: int = 0
    not_bonus: int = 0
    unmet_epochs: list[int] = field(default_factory=list)
    error: str | None = None

    @property
    def unmet_rate(self) -> float:
        return 100.0 * self.unmet / self.evaluated if self.evaluated else 0.0

    @property
    def not_bonus_rate(self) -> float:
        return 100.0 * self.not_bonus / self.evaluated if self.evaluated else 0.0


def latest_epoch(participants: list[dict], cluster: str) -> int:
    """SFDP 側が記録している最新 epoch を、参加者数件の stats の最大値から求める。"""
    best = 0
    checked = 0
    for p in participants:
        if p.get("state") != "Approved":
            continue
        try:
            detail = fetch_validator(p["mainnetBetaPubkey"])
        except RuntimeError:
            continue
        epochs = (detail.get(stats_key(cluster)) or {}).get("epochs") or {}
        if epochs:
            best = max(best, max(int(e) for e in epochs))
            checked += 1
        if checked >= 5:
            break
    if not best:
        raise RuntimeError("could not determine latest epoch")
    return best


def stats_key(cluster: str) -> str:
    return "mnStats" if cluster == "mainnet-beta" else "tnStats"


def build_row(participant: dict, cluster: str, window: range) -> Row:
    mn = participant["mainnetBetaPubkey"]
    tn = participant.get("testnetPubkey")
    pk = mn if cluster == "mainnet-beta" else tn
    row = Row(
        pubkey=pk or mn,
        name="",
        state=participant.get("state", ""),
        onboarding_epoch=participant.get("sfdp2OnboardingEpoch"),
    )
    if not pk:
        row.error = "no pubkey for cluster"
        return row
    try:
        detail = fetch_validator(mn)
    except RuntimeError as exc:
        row.error = str(exc)
        return row

    if cluster == "mainnet-beta":
        row.name = detail.get("mnName") or ""
    else:
        row.name = detail.get("tnName") or detail.get("mnName") or ""
    epochs = (detail.get(stats_key(cluster)) or {}).get("epochs") or {}

    for epoch in window:
        state = epochs.get(str(epoch))
        if state is None:
            row.missing += 1
            continue
        row.evaluated += 1
        row.counts[state] = row.counts.get(state, 0) + 1
        if state in UNMET_STATES:
            row.unmet += 1
            row.unmet_epochs.append(epoch)
        if state in NOT_BONUS_STATES:
            row.not_bonus += 1
    return row


def write_csv(path: Path, rows: list[Row], window: range) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "rank",
                "name",
                "pubkey",
                "state",
                "unmet_rate_pct",
                "unmet_epochs_count",
                "evaluated_epochs",
                "missing_epochs",
                "not_bonus_rate_pct",
                "bonus",
                "baseline",
                "none",
                "none_high_third_party_stake",
                "unmet_epoch_list",
                "window",
            ]
        )
        for i, r in enumerate(rows, 1):
            w.writerow(
                [
                    i,
                    r.name,
                    r.pubkey,
                    r.state,
                    f"{r.unmet_rate:.1f}",
                    r.unmet,
                    r.evaluated,
                    r.missing,
                    f"{r.not_bonus_rate:.1f}",
                    r.counts.get("Bonus", 0),
                    r.counts.get("Baseline", 0),
                    r.counts.get("None", 0),
                    r.counts.get("NoneHighThirdPartyStake", 0),
                    " ".join(str(e) for e in sorted(r.unmet_epochs, reverse=True)),
                    f"{window.start}-{window.stop - 1}",
                ]
            )


def write_markdown(path: Path, rows: list[Row], all_rows: list[Row], window: range, cluster: str, top: int) -> None:
    total = len(all_rows)
    flagged = [r for r in all_rows if r.unmet]
    pct = 100 * len(flagged) / total if total else 0.0
    lines = [
        f"# SFDP 基準未達率 ({cluster})",
        "",
        f"- 対象 epoch: `{window.start}` – `{window.stop - 1}` ({len(window)} epochs)",
        f"- 集計バリデータ: {total} 件",
        f"- 未達 (赤バツ) が 1 epoch 以上あるバリデータ: {len(flagged)} 件 ({pct:.1f}%)",
        f"- 本表に掲載: {len(rows)} 件",
        "",
        "未達率 = `None` (赤バツ) の epoch 数 / データのある epoch 数。",
        "`Baseline` (オレンジのチェック) は matching 未達だが residual は達成のため未達には数えていない",
        "（参考として not_bonus 率に含む）。",
        "",
        f"## 未達率ランキング (上位 {top} 件)",
        "",
        "| # | Name | 未達率 | 未達/評価 | not_bonus率 | 未達 epoch | Pubkey |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows[:top], 1):
        desc = sorted(r.unmet_epochs, reverse=True)
        eps = ", ".join(str(e) for e in desc[:12]) or "-"
        if len(desc) > 12:
            eps += f", … (+{len(desc) - 12})"
        lines.append(
            f"| {i} | {r.name or '(no name)'} | {r.unmet_rate:.1f}% | {r.unmet}/{r.evaluated} "
            f"| {r.not_bonus_rate:.1f}% | {eps} | `{r.pubkey}` |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--epochs", type=int, default=10, help="直近何 epoch を対象にするか (default: 10)")
    ap.add_argument("--end-epoch", type=int, default=None, help="集計終端 epoch (default: 最新)")
    ap.add_argument("--cluster", choices=["mainnet-beta", "testnet"], default="mainnet-beta")
    ap.add_argument("--states", default="Approved", help="対象の participant state (カンマ区切り, `all` で全件)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--rps", type=float, default=4.0, help="API リクエスト/秒の上限 (429 対策)")
    ap.add_argument("--min-rate", type=float, default=0.0, help="この未達率(%%)未満のバリデータを出力から除外")
    ap.add_argument(
        "--min-evaluated",
        type=int,
        default=None,
        help="評価対象 epoch 数がこの値未満のバリデータを除外 (default: 対象 epoch 数の半分)",
    )
    ap.add_argument("--top", type=int, default=50, help="Markdown / 標準出力に載せる件数")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--no-cache", action="store_true", help=f"{CACHE_DIR}/ のキャッシュを使わない")
    args = ap.parse_args()

    global LIMITER, USE_CACHE
    LIMITER = RateLimiter(args.rps)
    USE_CACHE = not args.no_cache

    print("fetching sfdp participants ...", file=sys.stderr)
    participants = fetch_json(PARTICIPANTS_URL)
    if args.states.lower() != "all":
        wanted = {s.strip() for s in args.states.split(",") if s.strip()}
        participants = [p for p in participants if p.get("state") in wanted]
    print(f"  -> {len(participants)} validators", file=sys.stderr)

    end = args.end_epoch or latest_epoch(participants, args.cluster)
    window = range(end - args.epochs + 1, end + 1)
    print(f"window: epoch {window.start}-{end} ({args.cluster})", file=sys.stderr)

    rows: list[Row] = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for row in pool.map(lambda p: build_row(p, args.cluster, window), participants):
            rows.append(row)
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{len(participants)}", file=sys.stderr)

    # 429 などで落ちた分はレートを落として直列リトライする
    for round_no in range(1, 4):
        failed_pks = {r.pubkey for r in rows if r.error}
        if not failed_pks:
            break
        print(f"retry round {round_no}: {len(failed_pks)} validators ...", file=sys.stderr)
        LIMITER = RateLimiter(min(args.rps, 2.0 / round_no))
        time.sleep(5 * round_no)
        by_pk = {
            r.pubkey: r
            for r in (build_row(p, args.cluster, window) for p in participants if p["mainnetBetaPubkey"] in failed_pks)
        }
        rows = [by_pk.get(r.pubkey, r) if r.error else r for r in rows]

    errors = [r for r in rows if r.error]
    rows = [r for r in rows if not r.error]
    if errors:
        print(f"warning: {len(errors)} validators failed to fetch", file=sys.stderr)
        for r in errors[:5]:
            print(f"  {r.pubkey}: {r.error}", file=sys.stderr)

    min_eval = args.min_evaluated if args.min_evaluated is not None else max(1, math.ceil(args.epochs / 2))
    excluded_new = [r for r in rows if r.evaluated < min_eval]
    rows = [r for r in rows if r.evaluated >= min_eval]
    if excluded_new:
        print(
            f"note: 評価 epoch 数 < {min_eval} のため {len(excluded_new)} 件を除外 "
            "(新規オンボード等。--min-evaluated 1 で含められる)",
            file=sys.stderr,
        )

    rows.sort(key=lambda r: (-r.unmet_rate, -r.unmet, r.name.lower()))
    kept = [r for r in rows if r.unmet_rate >= args.min_rate]

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{args.cluster}_e{window.start}-{end}"
    csv_path = out / f"sfdp_unmet_{tag}.csv"
    md_path = out / f"sfdp_unmet_{tag}.md"
    json_path = out / f"sfdp_unmet_{tag}.json"

    write_csv(csv_path, kept, window)
    write_markdown(md_path, kept, rows, window, args.cluster, args.top)
    json_path.write_text(
        json.dumps(
            {
                "cluster": args.cluster,
                "window": {"start": window.start, "end": end, "epochs": len(window)},
                "state_icon_map": STATE_ICON,
                "validators": [
                    {
                        "pubkey": r.pubkey,
                        "name": r.name,
                        "state": r.state,
                        "sfdp2OnboardingEpoch": r.onboarding_epoch,
                        "unmet_rate_pct": round(r.unmet_rate, 2),
                        "not_bonus_rate_pct": round(r.not_bonus_rate, 2),
                        "unmet": r.unmet,
                        "evaluated": r.evaluated,
                        "missing": r.missing,
                        "counts": r.counts,
                        "unmet_epochs": sorted(r.unmet_epochs, reverse=True),
                    }
                    for r in kept
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    flagged = [r for r in rows if r.unmet]
    print("", file=sys.stderr)
    print(f"epoch {window.start}-{end} / {len(rows)} validators", file=sys.stderr)
    print(f"未達 1 epoch 以上: {len(flagged)} 件", file=sys.stderr)
    print(f"wrote {csv_path}", file=sys.stderr)
    print(f"wrote {md_path}", file=sys.stderr)
    print(f"wrote {json_path}", file=sys.stderr)

    print(f"{'未達率':>7}  {'未達/評価':>9}  {'Name':<34} Pubkey")
    for r in kept[: args.top]:
        print(f"{r.unmet_rate:6.1f}%  {r.unmet:4d}/{r.evaluated:<4d}  {(r.name or '(no name)')[:34]:<34} {r.pubkey}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
