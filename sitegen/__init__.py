"""データに依存しない静的サイト生成基盤。

`render` がテンプレート展開、`registry` がダッシュボードの登録形式、`build` が
docs/ への書き出しと差分判定を担う。SFDP 固有の知識は `dashboards/` 側に置く。
"""

from .registry import BuildEnv, Dashboard, DashboardData
from .render import Template, TemplateError, escape, json_payload

__all__ = [
    "BuildEnv",
    "Dashboard",
    "DashboardData",
    "Template",
    "TemplateError",
    "escape",
    "json_payload",
]
