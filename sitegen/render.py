"""依存ゼロの最小テンプレート展開。

対応する構文は 3 つだけで、ループも条件分岐も持たない:

    {{ name }}            値を HTML エスケープして挿入
    {{& name }}           値をそのまま挿入（すでに安全な HTML / JSON 用）
    {{> partial.html }}   別テンプレートを再帰展開

繰り返しが必要な箇所は Python 側で HTML 断片を組み立てて `{{& ... }}` で差し込む。
テンプレートエンジンを入れないことで「pip install 不要」を保ちつつ、HTML / CSS / JS
を実ファイルとして扱えるようにするのが狙い。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TOKEN = re.compile(r"\{\{\s*([&>]?)\s*([\w.\-/]+)\s*\}\}")

MAX_INCLUDE_DEPTH = 10

_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}

# `<script>` 内の JSON で退避が必要な文字。`<` は `</script>` でパースを打ち切らせ、
# U+2028/2029 は JS のソース上で行終端として扱われる。
_JSON_UNSAFE = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    " ": "\\u2028",
    " ": "\\u2029",
}


class TemplateError(RuntimeError):
    pass


def escape(value) -> str:
    return "".join(_ESCAPES.get(c, c) for c in str(value))


def json_payload(value) -> str:
    """`<script>` の中に直接埋め込める JSON 文字列を返す。

    `json.dumps` は `<` をエスケープしないため、バリデータ名に `</script>` が
    入っているとそこで HTML のパースが打ち切られてページが壊れる。名前は各運営者が
    自由に設定できる値なので、`_JSON_UNSAFE` の文字はすべて `\\uXXXX` に退避させる。
    """
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    for char, repl in _JSON_UNSAFE.items():
        text = text.replace(char, repl)
    return text


class Template:
    """テンプレートディレクトリを 1 つ受け取り、そこからの相対名で展開する。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._cache: dict[str, str] = {}

    def source(self, name: str) -> str:
        if name not in self._cache:
            path = self.root / name
            if not path.is_file():
                raise TemplateError(f"template not found: {path}")
            self._cache[name] = path.read_text(encoding="utf-8")
        return self._cache[name]

    def render(self, name: str, ctx: dict, _depth: int = 0) -> str:
        if _depth > MAX_INCLUDE_DEPTH:
            raise TemplateError(f"include depth exceeded at {name} (循環参照の可能性)")

        def sub(m: re.Match) -> str:
            sigil, key = m.group(1), m.group(2)
            if sigil == ">":
                return self.render(key, ctx, _depth + 1)
            if key not in ctx:
                raise TemplateError(f"{name}: 未定義のトークン {{{{ {key} }}}}")
            value = ctx[key]
            return str(value) if sigil == "&" else escape(value)

        return TOKEN.sub(sub, self.source(name))
