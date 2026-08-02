"""api.solana.org を叩くための HTTP クライアント。

レート制御・ディスクキャッシュ・リトライを 1 つのインスタンスに閉じ込めてある。
以前はモジュールグローバルの `LIMITER` / `USE_CACHE` を呼び出し側から書き換えて
いたが、ダッシュボードが増えると設定の出所が追えなくなるため廃止した。
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "sfdp-monitor/1.0 (+https://github.com/DawnLabsTech)"

DEFAULT_CACHE_DIR = Path(".cache")
# SFDP のデータは epoch 単位（約 2〜2.5 日）でしか変わらないが、同一実行内での
# 使い回しと直後の再実行を速くするのが目的なので短めにしてある。
DEFAULT_CACHE_TTL = 3600.0


class FetchError(RuntimeError):
    """リトライを尽くしても取得できなかった。"""


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


class ApiClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.solana.org",
        rps: float = 4.0,
        retries: int = 6,
        timeout: int = 30,
        cache_dir: Path | None = DEFAULT_CACHE_DIR,
        cache_ttl: float = DEFAULT_CACHE_TTL,
    ):
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.timeout = timeout
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        self._limiter = RateLimiter(rps)

    def throttle(self, rps: float) -> None:
        """リトライラウンドでレートを落とすために使う。"""
        self._limiter = RateLimiter(rps)

    # --- HTTP ---------------------------------------------------------------

    def get_json(self, path: str, **query: str):
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return self._request(url)

    def post_json(self, path: str, payload: dict):
        """JSON を POST する。Solana の JSON-RPC がこれを要る。"""
        return self._request(self.base_url + path, payload=payload)

    def _request(self, url: str, payload: dict | None = None):
        last: Exception | None = None
        headers = {"User-Agent": USER_AGENT}
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        for attempt in range(self.retries):
            self._limiter.acquire()
            req = urllib.request.Request(url, data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                last = exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                exc.close()
                if exc.code == 429:
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0 * (attempt + 1)
                    time.sleep(delay)
                    continue
                if 400 <= exc.code < 500:
                    break  # 4xx はリトライしても変わらない
                time.sleep(1.5 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise FetchError(f"failed to fetch {url}: {last}")

    # --- ディスクキャッシュ -------------------------------------------------

    def cached_json(self, key: str, path: str, **query: str):
        """`key` 名でディスクにキャッシュしつつ取得する。

        バリデータ詳細は epoch の全履歴を含んで重いので、CLI で集計期間を変えて
        叩き直すときにキャッシュが効くようにしてある。
        """
        if self.cache_dir is None:
            return self.get_json(path, **query)

        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < self.cache_ttl:
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass  # 壊れたキャッシュは取り直す

        data = self.get_json(path, **query)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(cache_file)
        return data
