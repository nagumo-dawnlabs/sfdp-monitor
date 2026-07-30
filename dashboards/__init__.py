"""公開しているダッシュボードの一覧。

新しいダッシュボードを追加する手順:

1. `dashboards/<name>.py` に `collect(env) -> DashboardData` と
   `DASHBOARD = Dashboard(...)` を書く
2. `templates/<name>.html`（本文）と、必要なら `templates/<name>_footer.html` を置く
3. ページ固有の JS が必要なら `templates/assets/<name>.js` を追加し、
   `Dashboard.scripts` に並べる
4. 下の `DASHBOARDS` に追加する

レイアウト・アセット・差分判定・デプロイは `sitegen` 側が共通で面倒を見る。
"""

from . import criteria_miss

DASHBOARDS = [
    criteria_miss.DASHBOARD,
]

__all__ = ["DASHBOARDS", "criteria_miss"]
