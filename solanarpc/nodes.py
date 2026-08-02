"""`getClusterNodes` から、各バリデータのクライアント種別とバージョンを取る。

gossip の ContactInfo に載っている `clientId` が「何を動かしているか」の一次情報で、
1 リクエストでクラスタ全ノード分が返る。

`clientId` は列挙値で、まだ名前が登録されていないクライアントは `Unknown(<n>)` の形で
出てくる。その番号と実際のクライアントの対応は ibrl.wtf が持っている表と同じものを
使っている（ibrl.wtf の Client 列と 1 件ずつ突き合わせて一致を確認済み）。表に無い
番号はそのまま `Unknown(12)` のように出す — 勝手に「Agave」等へ丸めない。

BAM だけは gossip の値そのままでは足りない。BAM のバイナリを動かしていても実際に
BAM バリデータとして稼働しているとは限らないため、Jito の BAM 名簿に載っているかで
`BAM` と `Jito` を分ける（`client_label()` を参照）。
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"

# clientId -> 表示名。ibrl.wtf の Client 列と同じ対応表
CLIENT_NAMES = {
    "SolanaLabs": "Solana Labs",
    "JitoLabs": "Jito",
    "Frankendancer": "Frankendancer",
    "Agave": "Agave",
    "AgavePaladin": "Paladin",
    "Firedancer": "Firedancer",
    "AgaveBam": "BAM",
    "Sig": "Sig",
    "Unknown(4)": "Paladin",
    "Unknown(5)": "Firedancer",
    "Unknown(6)": "BAM",
    "Unknown(7)": "Sig",
    "Unknown(8)": "Rakurai",
    "Unknown(10)": "Harmonic Agave",
    "Unknown(11)": "Harmonic Frankendancer",
}

# BAM のバイナリを示す clientId。名簿と突き合わせて BAM か Jito かを決める
BAM_CLIENT_IDS = frozenset({"AgaveBam", "Unknown(6)"})


@dataclass(frozen=True)
class Node:
    """gossip に出ている 1 ノード。"""

    identity: str
    client_id: str  # 生の列挙値（"Agave" / "Unknown(8)" など）
    version: str


def fetch_cluster_nodes(client) -> dict[str, Node]:
    """identity pubkey 引きでクラスタ全ノードを返す。

    `client` は `solanaorg.client.ApiClient` と同じインターフェース。
    レスポンスは 1MB を超えるが、リクエストは 1 回で済む。
    """
    payload = client.post_json("", {"jsonrpc": "2.0", "id": 1, "method": "getClusterNodes"})
    if "error" in payload:
        raise RuntimeError(f"getClusterNodes failed: {payload['error']}")
    nodes = {}
    for row in payload.get("result") or []:
        pubkey = row.get("pubkey")
        if pubkey:
            nodes[pubkey] = Node(
                identity=pubkey,
                client_id=row.get("clientId") or "",
                version=row.get("version") or "",
            )
    return nodes


def client_label(node: Node | None, bam_identities: frozenset[str] | set[str]) -> str:
    """表示するクライアント名。分からなければ空文字。

    BAM のバイナリを動かしているノードは、Jito の BAM 名簿に載っているときだけ
    `BAM` とし、載っていなければ `Jito` とする（ibrl.wtf と同じ判定）。
    """
    if node is None or not node.client_id:
        return ""
    if node.client_id in BAM_CLIENT_IDS:
        return "BAM" if node.identity in bam_identities else "Jito"
    return CLIENT_NAMES.get(node.client_id, node.client_id)
