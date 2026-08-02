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

from . import criteria_miss, ibrl_criteria

# 並び順はハブでのカードの並びで、ビルド順でもある。criteria-miss を先に置くのは、
# ibrl-criteria が「criteria-miss が取り込んだロゴ」と「バリデータ詳細のキャッシュ」に
# 相乗りしているため（単体で走らせても動くが、その分だけ API を余計に叩く）。
DASHBOARDS = [
    criteria_miss.DASHBOARD,
    ibrl_criteria.DASHBOARD,
]

__all__ = ["DASHBOARDS", "criteria_miss", "ibrl_criteria"]
