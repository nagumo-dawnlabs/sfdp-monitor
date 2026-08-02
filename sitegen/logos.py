"""外部のバリデータロゴを取り込み、縮小して自サイトから配信できる形にする。

公開ページから外部ホストへリクエストを飛ばさないのがこのサイトの方針なので、
ロゴはビルド時にダウンロードして `docs/assets/logos/` に置く。原寸のままだと
355 件で 15MB 前後になるため 48px の WebP に落とす（実際の表示は 28px）。

- 取り込み済みのものは `index.json`（マニフェスト）で管理し、URL が変わらない限り
  再ダウンロードしない。日次ジョブでの差分はロゴが変わった分だけになる
- 縮小には Pillow が必要。無い環境では新規取り込みだけを諦め、既存のロゴは
  マニフェストごとそのまま維持する（依存が入っていないだけでページからロゴが
  一斉に消える、という壊れ方を避ける）
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

MANIFEST_NAME = "index.json"
SIZE = 48
# 表示は 28px なので、これを超える原本は取り込まない（壊れた URL や巨大画像の保険）
MAX_SOURCE_BYTES = 3 * 1024 * 1024
TIMEOUT = 20
USER_AGENT = "sfdp-monitor/1.0 (+https://github.com/DawnLabsTech)"


def _load_manifest(path: Path) -> dict[str, str]:
    """pubkey -> 取り込み元 URL。"""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        declared = resp.headers.get("Content-Length")
        if declared and int(declared) > MAX_SOURCE_BYTES:
            raise ValueError(f"too large: {int(declared) / 1024:.0f}KB")
        body = resp.read(MAX_SOURCE_BYTES + 1)
    if len(body) > MAX_SOURCE_BYTES:
        raise ValueError("too large")
    return body


def _shrink(body: bytes, size: int) -> bytes:
    """縦横比を保って size に収め、WebP にする。Pillow が必要。"""
    from PIL import Image

    with Image.open(BytesIO(body)) as im:
        im = im.convert("RGBA")
        im.thumbnail((size, size), Image.LANCZOS)
        buf = BytesIO()
        im.save(buf, format="WEBP", quality=82, method=6)
    return buf.getvalue()


def sync_logos(
    dest: Path,
    wanted: dict[str, str],
    *,
    size: int = SIZE,
    concurrency: int = 8,
    log=lambda msg: None,
) -> set[str]:
    """`wanted` (pubkey -> 取り込み元 URL) を dest に同期し、ロゴを持つ pubkey を返す。

    dest には `<pubkey>.webp` とマニフェスト `index.json` が置かれる。
    """
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path = dest / MANIFEST_NAME
    manifest = _load_manifest(manifest_path)

    keep: dict[str, str] = {}
    todo: list[tuple[str, str]] = []
    for pk, url in wanted.items():
        if manifest.get(pk) == url and (dest / f"{pk}.webp").is_file():
            keep[pk] = url
        else:
            todo.append((pk, url))

    if todo and not _pillow_available():
        # 依存が無いだけで既存のロゴを消してしまわない
        log(f"note: Pillow が無いため新規ロゴ {len(todo)} 件の取り込みをスキップ（既存 {len(keep)} 件は維持）")
        todo = []

    if todo:
        log(f"logos: {len(keep)} 件は再利用、{len(todo)} 件を取得 ...")

        def one(item: tuple[str, str]) -> tuple[str, str, str | None]:
            pk, url = item
            try:
                (dest / f"{pk}.webp").write_bytes(_shrink(_fetch(url), size))
            except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
                return pk, url, str(exc)
            return pk, url, None

        failures = 0
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for pk, url, error in pool.map(one, todo):
                if error:
                    failures += 1
                    if failures <= 3:
                        log(f"  skip logo {pk}: {error}")
                else:
                    keep[pk] = url
        if failures:
            log(f"logos: {failures} 件は取得できずロゴなしとして扱う")

    # 参加者から外れたバリデータのロゴを残さない
    for stale in dest.glob("*.webp"):
        if stale.stem not in keep:
            stale.unlink()

    manifest_path.write_text(
        json.dumps(dict(sorted(keep.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    log(f"logos: {len(keep)} 件")
    return set(keep)


def available_logos(dest: Path) -> set[str]:
    """既に `dest` に取り込まれているロゴの pubkey を返す（読むだけ）。

    ロゴを取り込む責務は `sync_logos()` を呼ぶダッシュボード 1 つに任せ、同じ
    バリデータを扱う別のダッシュボードはこの関数で「あるものを使う」に徹する。
    2 つのダッシュボードが同じディレクトリに `sync_logos()` すると、後から走った
    側が自分の対象外のロゴを「参加者から外れた」とみなして消してしまうため。
    """
    manifest = _load_manifest(dest / MANIFEST_NAME)
    return {pk for pk in manifest if (dest / f"{pk}.webp").is_file()}


def _pillow_available() -> bool:
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        return False
    return True
