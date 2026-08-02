"""SFDP (Solana Foundation Delegation Program) のエンドポイントと state 定義。

solana.org の各バリデータページ (Mainnet Beta セクション) に出ている epoch ごとの
アイコンは、API の `mnStats.epochs[<epoch>]` の state 値と 1:1 で対応する。
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .client import ApiClient, FetchError

PARTICIPANTS_PATH = "/api/community/v1/sfdp_participants"
VALIDATOR_PATH = "/api/validators/{pk}"

LAMPORTS = 1_000_000_000

# state 値 -> solana.org UI 上のアイコン
STATE_ICON = {
    "Bonus": "green-star",
    "Baseline": "orange-check",
    "None": "red-x",
    "NoneHighThirdPartyStake": "green-party-popper",
}

# state -> 埋め込み用 1 文字コード。ダッシュボードは epoch 列をこの文字列として持ち、
# Python 側の集計とブラウザ側の再集計はどちらもこの文字列だけを入力にする。
# どのコードを未達と数えるかは dashboards/criteria_miss.py の aggregate() が決める。
CODE = {
    "Bonus": "B",
    "Baseline": "L",
    "None": "N",
    "NoneHighThirdPartyStake": "H",
}
MISSING = "-"

CLUSTERS = ("mainnet-beta", "testnet")


def stats_key(cluster: str) -> str:
    return "mnStats" if cluster == "mainnet-beta" else "tnStats"


def calc_stats_key(cluster: str) -> str:
    return "mnCalculatedStats" if cluster == "mainnet-beta" else "tnCalculatedStats"


@dataclass
class ValidatorStates:
    """1 バリデータの、新しい epoch を先頭とした state 列。

    `states` の各文字は `CODE` / `MISSING` のいずれか。集計はすべてこの文字列を
    入力にするため、epoch マップを走査するコードは本モジュールの 1 箇所だけになる。
    """

    pubkey: str
    name: str
    participant_state: str
    stake_sol: int
    foundation_stake_sol: int
    states: str
    # solana.org が持っているロゴ画像の URL（外部ホスト。未設定なら空文字）
    image_url: str = ""


def fetch_participants(client: ApiClient, states: set[str] | None = None) -> list[dict]:
    participants = client.get_json(PARTICIPANTS_PATH)
    if states:
        participants = [p for p in participants if p.get("state") in states]
    return participants


def fetch_validator(client: ApiClient, pk: str) -> dict:
    return client.cached_json(pk, VALIDATOR_PATH.format(pk=pk), cacheStatus="enable")


def latest_epoch(client: ApiClient, participants: list[dict], cluster: str, samples: int = 12) -> int:
    """SFDP 側が記録している最新 epoch を、参加者数件の stats の最大値から求める。

    1 件でも取得に失敗すると epoch がずれるため、成功したサンプルが `samples` 件
    集まるまで見る（以前は 5 件で打ち切っていた）。
    """
    best = 0
    checked = 0
    key = stats_key(cluster)
    for p in participants:
        if p.get("state") != "Approved":
            continue
        try:
            detail = fetch_validator(client, p["mainnetBetaPubkey"])
        except FetchError:
            continue
        epochs = (detail.get(key) or {}).get("epochs") or {}
        if epochs:
            best = max(best, max(int(e) for e in epochs))
            checked += 1
        if checked >= samples:
            break
    if not best:
        raise FetchError("could not determine latest epoch")
    return best


def _sol(lamports) -> int:
    return round(int(lamports or 0) / LAMPORTS)


def _build(
    client: ApiClient,
    participant: dict,
    cluster: str,
    epochs_desc: list[int],
    *,
    require_history: bool = True,
) -> ValidatorStates | None:
    """取得できなければ FetchError を投げる。epoch データが無い参加者は None。

    `require_history=False` なら履歴の無い参加者も（state 列を空にして）返す。
    名前やロゴだけが要る呼び出し向け。
    """
    mn = participant["mainnetBetaPubkey"]
    detail = fetch_validator(client, mn)

    epoch_map = (detail.get(stats_key(cluster)) or {}).get("epochs") or {}
    if not epoch_map and require_history:
        return None  # オンボード前などで履歴なし。集計対象外

    calc = detail.get(calc_stats_key(cluster)) or {}
    pk = mn if cluster == "mainnet-beta" else participant.get("testnetPubkey")
    if cluster == "mainnet-beta":
        name = detail.get("mnName") or ""
        image = detail.get("mnImageUrl") or ""
    else:
        name = detail.get("tnName") or detail.get("mnName") or ""
        image = detail.get("tnImageUrl") or detail.get("mnImageUrl") or ""

    return ValidatorStates(
        pubkey=pk or mn,
        name=name,
        participant_state=participant.get("state", ""),
        stake_sol=_sol(calc.get("activated_stake_last_epoch")),
        foundation_stake_sol=_sol(calc.get("foundation_stake_last_epoch")),
        states="".join(CODE.get(epoch_map.get(str(e)), MISSING) for e in epochs_desc),
        image_url=image,
    )


def collect_states(
    client: ApiClient,
    participants: list[dict],
    cluster: str,
    end_epoch: int,
    history: int,
    *,
    concurrency: int = 4,
    retry_rounds: int = 3,
    require_history: bool = True,
    log=lambda msg: print(msg, file=sys.stderr),
) -> tuple[list[ValidatorStates], list[str]]:
    """全参加者の state 列を取得する。

    戻り値は (取得できた行, 最後まで失敗した pubkey)。429 で一部が欠けたページを
    そのまま公開してしまわないよう、失敗分は呼び出し側に明示的に返す。
    """
    epochs_desc = list(range(end_epoch, end_epoch - history, -1))
    by_pk: dict[str, ValidatorStates] = {}
    no_history: set[str] = set()
    pending = list(participants)

    def one(p: dict) -> tuple[dict, ValidatorStates | None, bool]:
        """(参加者, 取得できた行, 失敗したか) を返す。行が None かつ失敗でなければ履歴なし。"""
        try:
            return p, _build(client, p, cluster, epochs_desc, require_history=require_history), False
        except FetchError:
            return p, None, True

    for round_no in range(retry_rounds + 1):
        if not pending:
            break
        if round_no:
            # 429 で落ちた分はレートを落として再挑戦する
            client.throttle(max(0.5, 2.0 / round_no))
            log(f"  retry round {round_no}: {len(pending)} validators ...")

        failed: list[dict] = []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for i, (p, row, error) in enumerate(pool.map(one, pending), 1):
                if error:
                    failed.append(p)
                elif row is None:
                    no_history.add(p["mainnetBetaPubkey"])
                else:
                    by_pk[row.pubkey] = row
                if i % 50 == 0:
                    log(f"  {i}/{len(pending)}")

        pending = failed

    if no_history:
        log(f"note: {len(no_history)} validators have no epoch history (excluded)")
    return list(by_pk.values()), [p["mainnetBetaPubkey"] for p in pending]


def collect_profiles(
    client: ApiClient,
    participants: list[dict],
    cluster: str,
    *,
    concurrency: int = 4,
    log=lambda msg: print(msg, file=sys.stderr),
) -> tuple[list[ValidatorStates], list[str]]:
    """名前・ロゴ・stake だけを取る。epoch の state 列は空になる。

    SFDP 以外を主データにするダッシュボードが、pubkey に人が読める名前を
    付けるために使う。`fetch_validator` はディスクキャッシュ越しなので、同じ
    ビルドで criteria-miss が先に走っていれば追加の API 呼び出しは発生しない。
    """
    return collect_states(
        client,
        participants,
        cluster,
        end_epoch=0,
        history=0,  # state 列は要らない
        concurrency=concurrency,
        require_history=False,  # まだ 1 epoch も記録が無い参加者も名前は引ける
        log=log,
    )
