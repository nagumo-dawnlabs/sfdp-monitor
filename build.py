#!/usr/bin/env python3
"""公開ダッシュボード (docs/) を生成する唯一のエントリポイント。

    python3 build.py                    # 全ダッシュボード + ハブを生成
    python3 build.py --skip-unchanged   # 中身に差分がなければ書かない（CI 用）
    python3 build.py --only criteria-miss
    python3 build.py --fixture tests/fixtures/criteria-miss.json --out /tmp/site

登録されているダッシュボードは `dashboards/__init__.py` の DASHBOARDS を参照。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import solanarpc
from dashboards import DASHBOARDS
from sitegen.build import SiteConfig, build_site
from sitegen.registry import BuildEnv
from solanaorg import ApiClient, sfdp
from solanaorg.client import DEFAULT_CACHE_DIR

DEFAULT_REPO = "https://github.com/nagumo-dawnlabs/sfdp-monitor"


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", type=int, default=128, help="埋め込む epoch 数 (default: 128)")
    ap.add_argument("--cluster", choices=sfdp.CLUSTERS, default="mainnet-beta")
    ap.add_argument("--states", default="Approved", help="対象の participant state (カンマ区切り, `all` で全件)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--rps", type=float, default=4.0, help="API リクエスト/秒の上限 (429 対策)")
    ap.add_argument("--out", default="docs", help="出力ディレクトリ (default: docs)")
    ap.add_argument("--templates", default="templates")
    ap.add_argument("--logo", default="assets/logo-dawnlabs.png")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument(
        "--rpc-url",
        default=os.environ.get("SOLANA_RPC_URL") or solanarpc.DEFAULT_RPC_URL,
        help="クライアント種別を引く Solana JSON-RPC (環境変数 SOLANA_RPC_URL でも指定可)",
    )
    ap.add_argument("--no-cache", action="store_true", help=".cache/ を使わず必ず API を叩く")
    ap.add_argument("--only", action="append", metavar="SLUG", help="指定した slug だけビルドする（複数可）")
    ap.add_argument(
        "--fixture",
        action="append",
        metavar="PATH",
        default=[],
        help="API を叩かず、このスナップショット JSON からビルドする（複数可）",
    )
    ap.add_argument(
        "--skip-unchanged",
        action="store_true",
        help="データ・テンプレート・アセットに差分がなければ書き込まない（CI 用）",
    )
    ap.add_argument(
        "--max-missing-pct",
        type=float,
        default=2.0,
        help="取得失敗がこの割合(%%)を超えたら中止する。劣化したページを公開しないため (default: 2)",
    )
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    dashboards = DASHBOARDS
    if args.only:
        wanted = set(args.only)
        dashboards = [d for d in DASHBOARDS if d.slug in wanted]
        unknown = wanted - {d.slug for d in DASHBOARDS}
        if unknown:
            log(f"error: unknown dashboard slug: {', '.join(sorted(unknown))}")
            return 2
    if not dashboards:
        log("error: no dashboards selected")
        return 2

    # fixture は snapshot の "dashboard" フィールドで対象を判別する
    fixtures: dict[str, dict] = {}
    for path in args.fixture:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
        fixtures[snapshot["dashboard"]] = snapshot

    # fixture だけで全ダッシュボードが埋まるなら API クライアントは要らない
    needs_api = any(d.slug not in fixtures for d in dashboards)
    cache_dir = None if args.no_cache else DEFAULT_CACHE_DIR

    def make_client(base_url: str) -> ApiClient:
        """レート・キャッシュ設定を 1 か所に保ったまま、別ホスト用の口を作る。"""
        return ApiClient(base_url=base_url, rps=args.rps, cache_dir=cache_dir)

    client = make_client("https://api.solana.org") if needs_api else None

    env = BuildEnv(
        client=client,
        out_dir=Path(args.out),
        cluster=args.cluster,
        states=args.states,
        state_set=frozenset()
        if args.states.lower() == "all"
        else frozenset(s.strip() for s in args.states.split(",") if s.strip()),
        history=args.history,
        concurrency=args.concurrency,
        max_missing_pct=args.max_missing_pct,
        make_client=make_client if needs_api else None,
        rpc_url=args.rpc_url,
        fixtures=fixtures,
        log=log,
    )
    cfg = SiteConfig(
        out_dir=Path(args.out),
        template_dir=Path(args.templates),
        logo=Path(args.logo),
        repo_url=args.repo,
        skip_unchanged=args.skip_unchanged,
        # ハブは今回ビルドした分だけで作り直されるので、一部だけのときは触らせない
        write_hub=len(dashboards) == len(DASHBOARDS),
    )

    result = build_site(dashboards, env, cfg)
    log("")
    log(f"written: {', '.join(result.written) or '(none)'}")
    log(f"unchanged: {', '.join(result.unchanged) or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
