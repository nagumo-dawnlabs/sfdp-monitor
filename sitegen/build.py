"""ダッシュボード一覧を受け取り、静的サイトを 1 つのディレクトリに書き出す。

差分判定の考え方:

生成物のうち毎回変わるのは生成時刻だけなので、時刻を差し込む前の HTML と
データ JSON をまとめて SHA-256 にし、HTML 先頭のコメントに埋めておく。次回の
ビルドでこのハッシュが一致すれば書き込みをスキップする。テンプレートや CSS を
編集した場合もハッシュが変わるため、データが同じでもページは更新される。

結果として `docs/` に差分が出るのは「データ・テンプレート・アセットのいずれかが
実際に変わったとき」だけになり、生成時刻だけの空コミットが生まれない。
ページ上の "Data as of" は最後に中身が変わった時刻を意味する。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .registry import BuildEnv, Dashboard
from .render import Template, json_payload

# 生成時刻は指紋を取ってから差し替える。人が読む形と機械が読む ISO 形式の 2 種類
GENERATED_SENTINEL = "\x00GENERATED\x00"
GENERATED_ISO_SENTINEL = "\x00GENERATED_ISO\x00"
BUILD_HASH_RE = re.compile(r"<!-- build: ([0-9a-f]{16,}) -->")

ASSET_SUFFIXES = {".css", ".js", ".png", ".svg", ".woff2"}


@dataclass(frozen=True)
class SiteConfig:
    out_dir: Path
    template_dir: Path = Path("templates")
    logo: Path = Path("assets/logo-dawnlabs.png")
    site_title: str = "DawnLabs Dashboards"
    site_description: str = "Public dashboards built by DawnLabs on top of public Solana data."
    repo_url: str = "https://github.com/nagumo-dawnlabs/sfdp-monitor"
    dawnlabs_x: str = "https://x.com/dawnlabs00"
    skip_unchanged: bool = False


@dataclass
class BuildResult:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.written)


def build_site(dashboards: list[Dashboard], env: BuildEnv, cfg: SiteConfig) -> BuildResult:
    tpl = Template(cfg.template_dir)
    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # GitHub Pages の Jekyll に `_` 始まりのファイルを消されないようにする
    (out / ".nojekyll").write_text("", encoding="utf-8")

    versions = _sync_assets(cfg, out)
    # 公開ページなので、ビルドしたマシンのローカル時刻ではなく UTC で出す
    now = time.gmtime()
    stamps = {
        GENERATED_SENTINEL: time.strftime("%Y-%m-%d %H:%M UTC", now),
        GENERATED_ISO_SENTINEL: time.strftime("%Y-%m-%dT%H:%M:%SZ", now),
    }
    result = BuildResult()

    collected = []
    for dash in dashboards:
        env.log(f"[{dash.slug}] collecting ...")
        collected.append((dash, dash.collect(env)))

    for dash, data in collected:
        page = out / dash.slug / "index.html"
        data_path = out / dash.data_file
        payload = json.dumps(data.snapshot, ensure_ascii=False, indent=1, sort_keys=True) + "\n"

        ctx = _common_ctx(cfg, versions, asset_prefix="../")
        ctx.update(data.context)
        ctx["data_file"] = dash.data_file
        ctx["heading"] = dash.title
        ctx["page_title"] = f"{dash.title} — Powered by DawnLabs"
        ctx["og_title"] = dash.title
        ctx["description"] = dash.description
        ctx["breadcrumb"] = tpl.render("breadcrumb.html", ctx)
        ctx["freshness"] = tpl.render("freshness.html", ctx)
        ctx["script_tags"] = _script_tags(dash.scripts, versions, data.snapshot, prefix="../")
        ctx["body"] = tpl.render(dash.template, ctx)
        ctx["footer_note"] = tpl.render(dash.footer_template, ctx) if dash.footer_template else ""

        if _emit(tpl, page, ctx, extra=payload, skip_unchanged=cfg.skip_unchanged, stamps=stamps):
            data_path.parent.mkdir(parents=True, exist_ok=True)
            data_path.write_text(payload, encoding="utf-8")
            result.written.append(dash.slug)
            env.log(f"[{dash.slug}] wrote {page} ({page.stat().st_size / 1024:.0f} KB)")
        else:
            result.unchanged.append(dash.slug)
            env.log(f"[{dash.slug}] unchanged")

    # ハブはどれか 1 つでも更新されたときだけ書き直す（生成時刻だけの差分を避ける）
    if result.changed or not (out / "index.html").exists():
        _emit_hub(tpl, cfg, versions, collected, out, stamps)
        result.written.append("index")
        env.log(f"wrote {out / 'index.html'}")
    else:
        result.unchanged.append("index")

    return result


# --- ページ書き出し ---------------------------------------------------------


def _emit(tpl: Template, path: Path, ctx: dict, *, extra: str, skip_unchanged: bool, stamps: dict[str, str]) -> bool:
    """base.html を描画して `path` に書く。書いたら True、スキップしたら False。

    `ctx` および既に描画済みの本文には生成時刻の代わりに番兵が入っている。指紋を
    取ってから番兵を実時刻に差し替えるので、時刻だけの差分は指紋に影響しない。
    """
    draft = tpl.render("base.html", ctx)
    fingerprint = hashlib.sha256((draft + extra).encode()).hexdigest()

    if skip_unchanged and _build_hash(path) == fingerprint:
        return False

    html = draft
    for sentinel, value in stamps.items():
        html = html.replace(sentinel, value)
    html = html.replace("<head>", f"<head>\n<!-- build: {fingerprint} -->", 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return True


def _build_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    m = BUILD_HASH_RE.search(path.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def _emit_hub(tpl, cfg: SiteConfig, versions: dict, collected: list, out: Path, stamps: dict[str, str]) -> None:
    cards = "".join(
        tpl.render(
            "card.html",
            {
                "card_url": dash.url,
                "card_title": dash.title,
                "card_tagline": dash.tagline,
                "card_kpis": "".join(tpl.render("kpi.html", {"kpi_value": v, "kpi_label": k}) for v, k in data.stats),
            },
        )
        for dash, data in collected
    )
    ctx = _common_ctx(cfg, versions, asset_prefix="")
    ctx.update(
        heading=cfg.site_title,
        page_title=f"{cfg.site_title} — Powered by DawnLabs",
        og_title=cfg.site_title,
        description=cfg.site_description,
        breadcrumb="",
        script_tags="",
        # ハブには鮮度バッジを出さない（各カードの KPI とリンク先が主役）
        freshness="",
        cards=cards,
    )
    ctx["body"] = tpl.render("hub.html", ctx)
    ctx["footer_note"] = tpl.render("hub_footer.html", ctx)
    # ハブは常に書き直す（呼び出し側で更新有無を判断している）
    _emit(tpl, out / "index.html", ctx, extra="", skip_unchanged=False, stamps=stamps)


def _common_ctx(cfg: SiteConfig, versions: dict, *, asset_prefix: str) -> dict:
    logo = cfg.logo.name
    return {
        "asset_prefix": asset_prefix,
        "theme_version": versions.get("theme.css", ""),
        "logo_src": f"{asset_prefix}assets/{logo}?v={versions.get(logo, '')}",
        "repo_url": cfg.repo_url,
        "repo_name": cfg.repo_url.rsplit("/", 1)[-1],
        "dawnlabs_x": cfg.dawnlabs_x,
        "site_title": cfg.site_title,
        # 実際の時刻は _emit が最後に差し替える。本文・フッターにも同じ番兵が入る
        "generated": GENERATED_SENTINEL,
        "generated_iso": GENERATED_ISO_SENTINEL,
    }


def _script_tags(scripts: tuple[str, ...], versions: dict, snapshot: dict, *, prefix: str) -> str:
    """データを埋め込む inline script と、共通/固有 JS の読み込みタグ。

    DATA を先に定義してから JS を読み込む。ページ固有 JS は即時実行なので順序が重要。
    """
    tags = [f"<script>const DATA = {json_payload(snapshot)};</script>"]
    tags += [f'<script src="{prefix}assets/{name}?v={versions.get(name, "")}"></script>' for name in scripts]
    return "\n".join(tags)


# --- アセット ---------------------------------------------------------------


def _sync_assets(cfg: SiteConfig, out: Path) -> dict[str, str]:
    """templates/assets/* とロゴを out/assets/ に配置し、名前 -> 内容ハッシュを返す。

    ハッシュは `?v=` に付けてキャッシュを確実に破棄させるためのもの。
    """
    dest = out / "assets"
    dest.mkdir(parents=True, exist_ok=True)
    versions: dict[str, str] = {}

    sources = [p for p in sorted((cfg.template_dir / "assets").iterdir()) if p.suffix in ASSET_SUFFIXES]
    if cfg.logo.is_file():
        sources.append(cfg.logo)

    for src in sources:
        target = dest / src.name
        body = src.read_bytes()
        if not target.exists() or target.read_bytes() != body:
            shutil.copyfile(src, target)
        versions[src.name] = hashlib.sha256(body).hexdigest()[:8]

    # 消えたアセットを残さない
    keep = {s.name for s in sources}
    for stale in dest.iterdir():
        if stale.is_file() and stale.name not in keep:
            stale.unlink()

    return versions
