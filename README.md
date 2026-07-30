# sfdp-monitor

Solana の公開データをもとに DawnLabs が公開しているダッシュボードと、その生成基盤。

**公開サイト: https://nagumo-dawnlabs.github.io/sfdp-monitor/**

| ダッシュボード | 内容 |
|---|---|
| [SFDP Criteria Miss Rate](https://nagumo-dawnlabs.github.io/sfdp-monitor/criteria-miss/) | SFDP 参加バリデータが直近 X epoch のうち何割で基準を満たさなかったか |

実行時の依存パッケージなし（Python 3.10+ 標準ライブラリのみ）。ページ側も外部リソースを一切読まない
（バリデータロゴもビルド時に取り込んで同居配信するので、閲覧者の IP が第三者に渡らない）。
ロゴの縮小にだけ Pillow を使うが、これはビルド時のみの依存で、無い環境でも既存のロゴを維持したまま動く。

```bash
python3 build.py                      # docs/ を再生成
python3 build.py --skip-unchanged     # 中身に差分がなければ書かない（CI と同じ挙動）
python3 -m http.server -d docs 8000   # localhost:8000 で確認
```

---

## ディレクトリ構成

```
build.py                    ビルドの唯一のエントリポイント
sfdp_status.py              アドホック集計 CLI（CSV / Markdown / JSON を出す）

solanaorg/                  api.solana.org のデータ取得層
  client.py                   ApiClient: レート制御 + ディスクキャッシュ + リトライ
  sfdp.py                     SFDP のエンドポイント・state 定義・state 列の組み立て

sitegen/                    データに依存しない静的サイト生成基盤
  render.py                   依存ゼロの最小テンプレート展開
  registry.py                 Dashboard / DashboardData / BuildEnv の型
  build.py                    docs/ への書き出し・差分判定・アセット配置
  logos.py                    外部画像の取り込み・縮小・マニフェスト管理

dashboards/                 ダッシュボードごとの実装
  __init__.py                 DASHBOARDS（登録一覧）
  criteria_miss.py            収集・集計・CLI レポート

templates/                  HTML / CSS / JS の実ファイル
  base.html                   共通レイアウト（masthead / footer / Powered by DawnLabs）
  hub.html                    トップのダッシュボード一覧
  criteria_miss.html          本文
  assets/theme.css            全ページ共通のデザイントークンとコンポーネント
  assets/table.js             ソート / フィルタ / 段階表示 / CSV 書き出しの共通実装
  assets/criteria_miss.js     このページ固有の集計と行描画

docs/                       生成物（GitHub Pages が main の /docs を公開）
  index.html                  ハブ
  criteria-miss/index.html    ダッシュボード
  data/criteria-miss.json     機械可読なスナップショット（差分判定の真実）
  assets/                     theme.css / *.js / DawnLabs ロゴ（全ページで共有）
  assets/logos/               バリデータロゴ 48px WebP + index.json（取り込み元 URL）

tests/                      pytest（API を叩かない）
```

### 設計の要点

- **HTML / CSS / JS は実ファイル**。Python の文字列に埋め込まないので、補完・lint・
  シンタックスハイライトが効き、ページを増やしてもデザインが分岐しない
- **集計ロジックは 1 箇所**。`dashboards/criteria_miss.py` の `aggregate()` が唯一の定義で、
  `templates/assets/criteria_miss.js` が同一アルゴリズムをブラウザ側に持つ（相互参照コメントあり）。
  CLI とダッシュボードの数字が食い違うことが構造的に起きない
- **共有アセット**。`docs/assets/` に 1 本ずつ置いて全ページから `?v=<内容ハッシュ>` 付きで参照する。
  ロゴを data URI で各ページに埋める方式をやめたので、ページを増やしても重複しない
- **データは HTML にも埋め込む**。単一リクエストで完結し、`file://` で開いても動く。
  `docs/data/*.json` は差分判定と再利用（スプレッドシート取り込み、過去比較）のためのもの
- **外部リクエストゼロ**。バリデータロゴは `mnImageUrl`（media.stakewiz.com / s3.amazonaws.com 配信）を
  ビルド時に取り込み、48px の WebP に縮小して `docs/assets/logos/` から出す。原寸のままだと 355 件で
  約 15MB になるが、縮小後は合計 1MB 未満。`index.json` に取り込み元 URL を記録し、URL が変わらない限り
  再ダウンロードしないので、日次ジョブでの差分はロゴが変わった分だけになる

---

## ダッシュボードを追加する

1. `dashboards/<name>.py` に `collect(env) -> DashboardData` と `DASHBOARD = Dashboard(...)` を書く
2. `templates/<name>.html`（本文）と、必要なら `templates/<name>_footer.html`（出典・免責）を置く
3. ページ固有の JS が必要なら `templates/assets/<name>.js` を追加し、`Dashboard.scripts` に並べる
4. `dashboards/__init__.py` の `DASHBOARDS` に追加する

レイアウト・共通アセット・差分判定・ハブへの掲載・デプロイは `sitegen` が面倒を見る。
`DashboardData.stats` に `(値, ラベル)` を入れると、それがハブのカードの KPI になる。

`collect()` に渡る `BuildEnv` は `client`（`ApiClient`）・`out_dir`・`cluster`・`history`・
`concurrency`・`max_missing_pct`・`want_assets`・`fixtures`・`log` を持つ。データ源が SFDP 以外でも、
`solanaorg` に倣って取得層を 1 パッケージ足せばよい。画像などページから参照する副生成物が必要なら
`out_dir` の下に置き、`sitegen.logos.sync_logos()` のようなユーティリティを使う。

`DashboardData.context` には **`coverage`（鮮度バッジに出す「何をどこまで見ているか」の 1 行）が必須**。
未定義のトークンはビルドエラーになるので、忘れれば CI で落ちる。

---

## テンプレート構文

`sitegen/render.py` が対応するのは 3 つだけで、ループも条件分岐もない。

| 構文 | 意味 |
|---|---|
| `{{ name }}` | 値を HTML エスケープして挿入 |
| `{{& name }}` | 値をそのまま挿入（すでに安全な HTML / JSON 用） |
| `{{> partial.html }}` | 別テンプレートを再帰展開 |

繰り返しが必要な箇所（ハブのカード・KPI）は小さな部分テンプレートを Python 側で `join` する。
未定義のトークンを参照するとエラーになるので、タイポが黙って空文字になることはない。

`<script>` に埋め込む JSON は `json_payload()` を通す。`json.dumps` は `<` をエスケープしないため、
バリデータ名に `</script>` が含まれていると HTML のパースが打ち切られてページが壊れる。
名前は各運営者が自由に設定できる値なので、`<` `>` `&` と U+2028/2029 を退避させている。

---

## 自動更新

`.github/workflows/update.yml` が **毎日 03:00 UTC（12:00 JST）** に `build.py` を実行し、
差分があれば `docs/` をコミット・push する（Pages が自動で再デプロイ）。

- SFDP のデータは epoch 単位（約2〜2.5日）でしか変わらず、さらに API 反映が約2 epoch 遅れるため 1 日 1 回で十分
- **差分がない日はコミットしない**。生成時刻を差し込む前の HTML とデータ JSON の SHA-256 を
  `<!-- build: … -->` に埋めており、`--skip-unchanged` はこれが一致したら書き込みをスキップする。
  テンプレートや CSS を編集した場合はハッシュが変わるので、データが同じでもページは更新される
- 結果として、ページ上部の **Data as of バッジ**は「最後にデータが変わった時刻」を意味する。
  UTC の絶対時刻を HTML に出し（JS 無効でも読める）、`<time datetime>` から相対時間（"updated 3 hours ago"）を
  JS が補う
- **取得失敗が 2% を超えたらビルドを中止する**（`--max-missing-pct`）。429 で一部バリデータが
  抜け落ちたページを公開して、件数が理由不明に変動するのを防ぐ
- Runner の IP は共有なので 429 を避けて `--rps 2 --concurrency 3` で実行（所要 5〜10 分）
- 手動実行は Actions タブの **Run workflow**（`force` を on にすると差分がなくても再生成）
- **ジョブが失敗したら issue を自動起票**する（同じ issue が open なら追記のみ）

`.github/workflows/ci.yml` が push / PR で `ruff` + `pytest` + fixture からのスモークビルドを走らせる。
API を叩かないので数秒で終わる。

ローカルから手動更新する場合は `python3 build.py && git add docs && git commit -m "update data" && git push`。

---

## アドホック集計 CLI

```bash
python3 sfdp_status.py --epochs 10                                        # 直近 10 epoch（API から取得）
python3 sfdp_status.py --epochs 30 --min-rate 10                          # 未達率 10% 以上のみ
python3 sfdp_status.py --from docs/data/criteria-miss.json --epochs 64     # API を叩かず即集計
python3 sfdp_status.py --from docs/data/criteria-miss.json --epochs 10 --end-epoch 990   # 過去時点の再現
python3 sfdp_status.py --epochs 10 --cluster testnet
```

`--from` にコミット済みのスナップショットを渡すと数十ミリ秒で終わる。ダッシュボードと同じ
`aggregate()` を通すので、ブラウザで同じ窓を選んだときの表と数字が一致する。

| オプション | 既定値 | 説明 |
|---|---|---|
| `--epochs N` | `10` | 直近何 epoch を対象にするか |
| `--end-epoch N` | 最新 | 集計終端 epoch（過去時点の再現に使う） |
| `--from PATH` | — | API の代わりに使うスナップショット JSON |
| `--cluster` | `mainnet-beta` | `mainnet-beta` / `testnet` |
| `--states` | `Approved` | 対象の participant state。カンマ区切り。`all` で全件 |
| `--min-rate PCT` | `0` | この未達率未満のバリデータを出力から除外 |
| `--min-evaluated N` | `epochs/2` | 評価 epoch 数がこれ未満のバリデータを除外（新規オンボード除け） |
| `--top N` | `50` | Markdown / 標準出力に載せる件数 |
| `--rps` / `--concurrency` | `4` / `4` | API レート（`api.solana.org` は 429 を返すので上げすぎない） |
| `--no-cache` | off | `.cache/` を使わず必ず API を叩く |
| `--out-dir` | `out` | 出力先（git 管理外） |

`out/sfdp_unmet_<cluster>_e<start>-<end>.{csv,md,json}` を生成する。
`csv` はダッシュボードのダウンロード CSV と同じ列構成、`json` には未達 epoch の一覧も入る。

初回の API 実行は 404 件で約 3〜5 分。バリデータ詳細は `.cache/` に 1 時間キャッシュされる。

---

## 判定ロジック

API `GET https://api.solana.org/api/validators/<mainnetBetaPubkey>?cacheStatus=enable` の
`mnStats.epochs` は `{ "<epoch>": "<state>" }` の全履歴マップで、この state が solana.org 上の
アイコンと 1:1 で対応する（フロントエンドのバンドル `ValidatorEpochStates` および実ページで検証済み）。

| state | UI アイコン | 意味 | 本ツールの扱い | コード |
|---|---|---|---|---|
| `Bonus` | 🟢 緑の星 | matching 基準を満たした | 達成 | `B` |
| `Baseline` | 🟠 オレンジのチェック | matching は未達、residual のみ達成 | **未達に数えない**（`not_bonus` にのみ計上） | `L` |
| `None` | 🔴 赤いバツ | 基準未達 | **未達** | `N` |
| `NoneHighThirdPartyStake` | 🟢 緑のクラッカー | third party stake が十分で SFDP stake 不要 | 達成扱い | `H` |
| （マップに無い） | — | オンボード前 / delinquent で記録なし | 分母から除外 | `-` |

- **未達率** = `None` の epoch 数 ÷ データのある epoch 数
- **not_bonus 率** = (`None` + `Baseline`) ÷ データのある epoch 数
- **連続未達 (streak)** = 最新 epoch から連続する `None` の数。**データなし epoch は連続を途切れさせない**
  （記録が無いだけで達成したわけではないため）。`Bonus` / `Baseline` / `NoneHighThirdPartyStake` は切る
- 表示色は未達率 **20% 以上で赤 / 15% 以上でオレンジ / 10% 以上で黄**、それ未満はグレー、0% は最も薄い。
  しきい値は `templates/assets/table.js` の `RATE_TIERS` が単一の定義
- 分母が要求した窓より小さくなりうる（新規オンボード等）ため、既定では窓の半分以上のデータがある
  バリデータだけを表示する

delinquent 判定は別 API (`/api/validators/vote-credits`) 由来で `epochs` マップには入らないため、
本ツールでは `-`（データなし）に落ちる。

各 epoch の state を 1 文字コードの列（新しい epoch が先頭）にして持つのがこのツールの中心的な
データ表現で、集計はすべてこの文字列を入力にする。epoch マップを走査するコードは
`solanaorg/sfdp.py` の 1 箇所だけ。

---

## データソース

- 参加者一覧: `GET https://api.solana.org/api/community/v1/sfdp_participants`（[公式ドキュメント](https://solana.org/delegation-api-docs#sfdp-participants)）
  - state 内訳（2026-07 時点）: Approved 404 / TestnetOnboarded 123 / Pending 11 / Retired 3,450 / Rejected 6,974
- バリデータ詳細: `GET https://api.solana.org/api/validators/<pubkey>?cacheStatus=enable`（solana.org が内部で使用。公式ドキュメント外）

本サイトは公開 API データの非公式な集計であり、Solana Foundation の発行物ではない。

---

## 開発

```bash
python3 -m venv .venv && .venv/bin/pip install ruff pytest pillow
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest

# API を叩かないスモークビルド
python3 build.py --fixture tests/fixtures/criteria-miss.json --out /tmp/site --history 64
```

`pillow` はロゴ縮小にだけ必要（無くても既存のロゴを維持したままビルドできる）。テストは
ネットワークを一切使わない。

`tests/fixtures/criteria-miss.json` は実データから特徴的な 22 件を抜き、名前に `</script>` を含む
合成レコードを 1 件足したもの。テンプレートの取りこぼしと script 注入の回帰を同時に見ている。
