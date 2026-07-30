#!/usr/bin/env python3
"""SFDP バリデータの epoch 別基準未達率を、任意の期間で集計してレポートに落とす CLI。

公開ダッシュボード (`build.py`) と同じ `dashboards.criteria_miss.aggregate()` を通すため、
両者の数字は構造的に一致する。

    python3 sfdp_status.py --epochs 10
    python3 sfdp_status.py --epochs 64 --min-rate 10
    python3 sfdp_status.py --from docs/data/criteria-miss.json --epochs 30
    python3 sfdp_status.py --from docs/data/criteria-miss.json --epochs 10 --end-epoch 990

`--from` にコミット済みのスナップショットを渡すと API を叩かずに即座に集計できる。
`--end-epoch` を併せて指定すれば過去時点の再現になる（スナップショットが持つ履歴の範囲内）。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from dashboards import criteria_miss as cm
from sitegen.registry import BuildEnv
from solanaorg import ApiClient, sfdp
from solanaorg.client import DEFAULT_CACHE_DIR

# --end-epoch 指定時に API から取り込む epoch 数。これより古い時点を見るなら
# より長い履歴を持つスナップショットを --from で渡す
HISTORY_FOR_BACKFILL = 512


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--epochs", type=int, default=10, help="直近何 epoch を対象にするか (default: 10)")
    ap.add_argument("--end-epoch", type=int, default=None, help="集計終端 epoch (default: 最新)")
    ap.add_argument("--cluster", choices=sfdp.CLUSTERS, default="mainnet-beta")
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
    ap.add_argument("--no-cache", action="store_true", help=f"{DEFAULT_CACHE_DIR}/ のキャッシュを使わない")
    ap.add_argument(
        "--from",
        dest="snapshot",
        metavar="PATH",
        help="API の代わりに使うスナップショット JSON (docs/data/criteria-miss.json など)",
    )
    return ap.parse_args(argv)


def load_snapshot(args) -> dict:
    """スナップショットを読む、または API から取得する。"""
    if args.snapshot:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        log(f"snapshot: {args.snapshot} ({len(snapshot['validators'])} validators, epoch {snapshot['window']['end']})")
        return snapshot

    env = BuildEnv(
        client=ApiClient(rps=args.rps, cache_dir=None if args.no_cache else DEFAULT_CACHE_DIR),
        out_dir=Path(args.out_dir),
        # CLI は CSV / Markdown を出すだけなのでロゴは取り込まない
        want_assets=False,
        cluster=args.cluster,
        states=args.states,
        state_set=frozenset()
        if args.states.lower() == "all"
        else frozenset(s.strip() for s in args.states.split(",") if s.strip()),
        # --end-epoch で過去に遡る場合、最新 epoch はまだ分からないので余裕を取る。
        # epoch マップは 1 リクエストで全履歴が返るため、長く取っても API 負荷は変わらない
        history=args.epochs if args.end_epoch is None else HISTORY_FOR_BACKFILL,
        concurrency=args.concurrency,
        max_missing_pct=100.0,  # CLI は欠損があっても手元で見たいので止めない
        log=log,
    )
    return cm.collect(env).snapshot


def shift_to(snapshot: dict, end_epoch: int | None) -> tuple[dict, int]:
    """`end_epoch` を終端に合わせて state 列を前方に詰める。戻り値は (snapshot, end)。"""
    snap_end = snapshot["window"]["end"]
    if end_epoch is None or end_epoch == snap_end:
        return snapshot, snap_end
    if end_epoch > snap_end:
        raise SystemExit(f"error: --end-epoch {end_epoch} はスナップショットの最新 epoch {snap_end} より新しい")
    offset = snap_end - end_epoch
    shifted = dict(snapshot)
    shifted["validators"] = [{**v, "s": v["s"][offset:]} for v in snapshot["validators"]]
    return shifted, end_epoch


def main(argv=None) -> int:
    args = parse_args(argv)
    snapshot, end = shift_to(load_snapshot(args), args.end_epoch)
    start = end - args.epochs + 1

    min_eval = args.min_evaluated if args.min_evaluated is not None else max(1, math.ceil(args.epochs / 2))
    pool = cm.report_rows(snapshot, args.epochs, min_eval, 0.0)
    kept = [r for r in pool if r.counts.miss_rate >= args.min_rate]

    excluded = len(snapshot["validators"]) - len(pool)
    if excluded:
        log(
            f"note: 評価 epoch 数 < {min_eval} のため {excluded} 件を除外 (新規オンボード等。--min-evaluated 1 で含められる)"
        )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{snapshot['cluster']}_e{start}-{end}"
    paths = {ext: out / f"sfdp_unmet_{tag}.{ext}" for ext in ("csv", "md", "json")}

    cm.write_csv(paths["csv"], kept, start, end)
    cm.write_markdown(paths["md"], kept, pool, start, end, snapshot["cluster"], args.top)
    cm.write_json(paths["json"], kept, start, end, snapshot["cluster"])

    flagged = [r for r in pool if r.counts.none]
    log("")
    log(f"epoch {start}-{end} / {len(pool)} validators")
    log(f"未達 1 epoch 以上: {len(flagged)} 件")
    for p in paths.values():
        log(f"wrote {p}")

    print(f"{'未達率':>7}  {'未達/評価':>9}  {'Name':<34} Pubkey")
    for r in kept[: args.top]:
        c = r.counts
        print(f"{c.miss_rate:6.1f}%  {c.none:4d}/{c.evaluated:<4d}  {r.name[:34]:<34} {r.validator['p']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
