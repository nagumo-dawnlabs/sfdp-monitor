"""ダッシュボードの登録形式。

ここにはデータ固有の知識を置かない。実際の一覧は `dashboards/__init__.py` の
`DASHBOARDS` が持ち、`sitegen.build` はそれを引数で受け取る（sitegen 側から
dashboards を import すると循環参照になるため）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BuildEnv:
    """1 回のビルド全体に共通する設定。`collect` に渡される。"""

    client: Any | None  # solanaorg.ApiClient（fixture ビルド時は None）
    # 出力先。ロゴのようにページから参照する副生成物を書くダッシュボードが使う
    out_dir: Path
    cluster: str
    states: str  # `--states` の生の指定。注記への表示に使う
    state_set: frozenset[str]  # 空集合なら全 state
    history: int
    concurrency: int
    max_missing_pct: float
    # ページから参照する画像などの副生成物を取り込むか。CLI レポートだけなら不要
    want_assets: bool = True
    # slug -> スナップショット。API を叩かずにビルドしたいとき（テスト・CI）に使う
    fixtures: dict[str, dict] = field(default_factory=dict)
    log: Callable[[str], None] = lambda msg: None


@dataclass
class DashboardData:
    """`collect` の戻り値。"""

    # docs/data/<slug>.json にそのまま書き出し、HTML にも同じ内容を埋め込む。
    # 差分判定はこの dict の比較で行うので、生成時刻のような毎回変わる値は入れない。
    snapshot: dict
    # テンプレート固有の追加トークン（{{ ... }} で参照される）
    context: dict = field(default_factory=dict)
    # ハブページのカードに出す KPI。(値, ラベル) の並び
    stats: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Dashboard:
    """1 ページ分の定義。

    新しいダッシュボードを足すときは `dashboards/<name>.py` にこのインスタンスを
    1 つ作り、`dashboards/__init__.py` の `DASHBOARDS` に追加するだけでよい。
    レイアウト・アセット・差分判定・デプロイは共通基盤が面倒を見る。
    """

    slug: str  # "criteria-miss" -> docs/criteria-miss/index.html
    title: str
    tagline: str  # ハブのカードに出す 1 行説明
    description: str  # <meta name="description">
    template: str  # templates/ 配下のファイル名（本文）
    collect: Callable[[BuildEnv], DashboardData]
    scripts: tuple[str, ...] = ()  # 読み込む assets/*.js（順序が意味を持つ）
    footer_template: str | None = None  # フッターの出典・免責の注記

    @property
    def url(self) -> str:
        return f"{self.slug}/"

    @property
    def data_file(self) -> str:
        return f"data/{self.slug}.json"
