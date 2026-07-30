# sfdp-monitor

SFDP (Solana Foundation Delegation Program) 参加バリデータについて、**直近 X epoch で基準を満たさなかった割合**を算出してリスト化するツール。

solana.org の各バリデータページ（例: [Lion3d](https://solana.org/sfdp-validators/CVvaeDPR2o7P1eawG5c9TPFLzSXAewwPovPmREaEL4Cm)）の "Mainnet Beta" セクションに並ぶ epoch 別アイコンを、そのままデータとして集計する。

## 使い方

```bash
python3 sfdp_status.py --epochs 10                  # 直近 10 epoch
python3 sfdp_status.py --epochs 30 --min-rate 10    # 直近 30 epoch、未達率 10% 以上のみ
python3 sfdp_status.py --epochs 10 --cluster testnet
python3 sfdp_status.py --epochs 64 --states Approved,TestnetOnboarded
```

依存パッケージなし（Python 3.10+ 標準ライブラリのみ）。

### 主なオプション

| オプション | 既定値 | 説明 |
|---|---|---|
| `--epochs N` | `10` | 直近何 epoch を対象にするか |
| `--end-epoch N` | 最新 | 集計終端 epoch（過去時点の再現に使う） |
| `--cluster` | `mainnet-beta` | `mainnet-beta` / `testnet` |
| `--states` | `Approved` | 対象の participant state。カンマ区切り。`all` で全 10,962 件 |
| `--min-rate PCT` | `0` | この未達率未満のバリデータを出力から除外 |
| `--min-evaluated N` | `epochs/2` | 評価 epoch 数がこれ未満のバリデータを除外（新規オンボード除け） |
| `--top N` | `50` | Markdown / 標準出力に載せる件数 |
| `--rps` / `--concurrency` | `4` / `4` | API レート（`api.solana.org` は 429 を返すので上げすぎない） |
| `--no-cache` | off | `.cache/` を使わず必ず API を叩く |

### 出力

`out/sfdp_unmet_<cluster>_e<start>-<end>.{csv,md,json}` を生成する。

- `csv` — スプレッドシート取り込み用。全指標 + 未達 epoch 一覧
- `md` — 未達率ランキング表（サマリ付き）
- `json` — 後段処理用

初回実行は 404 件で約 3〜5 分。バリデータ詳細は `.cache/` に 1 時間キャッシュされるため、
同じ期間内で `--epochs` を変えて再集計するのは数秒で終わる。

## 判定ロジック

API `GET https://api.solana.org/api/validators/<mainnetBetaPubkey>?cacheStatus=enable` の
`mnStats.epochs` は `{ "<epoch>": "<state>" }` の全履歴マップで、この state が solana.org 上の
アイコンと 1:1 で対応する（フロントエンドのバンドル `ValidatorEpochStates` および実ページで検証済み）。

| state | UI アイコン | 意味 | 本ツールの扱い |
|---|---|---|---|
| `Bonus` | 🟢 緑の星 | matching 基準を満たした | 達成 |
| `Baseline` | 🟠 オレンジのチェック | matching は未達、residual のみ達成 | **未達に数えない**（`not_bonus` にのみ計上） |
| `None` | 🔴 赤いバツ | 基準未達 | **未達** |
| `NoneHighThirdPartyStake` | 🟢 緑のクラッカー | third party stake が十分で SFDP stake 不要 | 達成扱い |

- **未達率** = `None` の epoch 数 ÷ データのある epoch 数
- **not_bonus 率** = (`None` + `Baseline`) ÷ データのある epoch 数
- epoch がマップに存在しない場合は `missing` として分母から除外する（オンボード前、または delinquent で記録なし）

delinquent 判定は別 API (`/api/validators/vote-credits`) 由来で `epochs` マップには入らないため、
本ツールでは `missing` に落ちる。

## データソース

- 参加者一覧: `GET https://api.solana.org/api/community/v1/sfdp_participants`（[公式ドキュメント](https://solana.org/delegation-api-docs#sfdp-participants)）
  - state 内訳（2026-07 時点）: Approved 404 / TestnetOnboarded 123 / Pending 11 / Retired 3,450 / Rejected 6,974
- バリデータ詳細: `GET https://api.solana.org/api/validators/<pubkey>?cacheStatus=enable`（solana.org が内部で使用。公式ドキュメント外）
- 参考: `GET https://api.solana.org/api/validators/list?limit=40`（集計済み指標のみ。epoch 別の内訳は含まない）
