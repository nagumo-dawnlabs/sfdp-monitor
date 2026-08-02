# sfdp-monitor

公開ダッシュボード <https://nagumo-dawnlabs.github.io/sfdp-monitor/> のリポジトリ。

## コミット・プッシュ

**このリポジトリでは、変更したら毎回コミットして `main` に push する。**

GitHub Pages が `main` の `/docs` をそのまま配信しているので、push するまで公開サイトは
古いままになる。ローカルで直っていても「反映されていない」状態が残るため、確認待ちで
止めずに最後まで通す。

手順:

1. テンプレート・スクリプトを変更したら `python3 build.py` で `docs/` を再生成する
   （`docs/` は生成物だが追跡対象。これを忘れると公開サイトだけ取り残される）
2. `ruff check . && ruff format --check . && pytest` を通す
3. コミット（英語・命令形）して `git push origin main`

`main` に直接コミットしてよい。デイリーの GitHub Actions も同じことをしている。

## 補足

- 実行時の依存パッケージなし。lint / test / ロゴ縮小にだけ ruff・pytest・Pillow を使う
  （手元に無ければ `uv run --with pytest --with pillow --with ruff --python 3.12 ...`）
- ページ側も外部リソースを読まない。CDN・Web フォント・外部画像を足さないこと
- 集計ロジックは Python とブラウザの二重実装。片方を変えたら必ず両方直す
  - `dashboards/criteria_miss.py` の `aggregate()` ⇔ `templates/assets/criteria_miss.js` の `aggregate()`
  - `dashboards/ibrl_criteria.py` の `summarize()` / `score_class()` / `ms_class()` ⇔
    `templates/assets/ibrl_criteria.js` の `summarize()` / `scoreClass()` / `msClass()`
- ibrl-criteria の主軸は Trillium の `slot_duration_median`（ms・低いほど良い）。IBRL 総合スコアは
  表示しない。スコア列（高いほど良い）と色の向きが逆なので、`v-*` クラスを使うときは要注意
- **表の数字は epoch も含めて Trillium 1 か所から取る**。内訳スコアは ibrl.wtf と同値が
  Trillium に入っているため（全件一致を確認済み）。列ごとに出所が混ざる状態に戻さないこと
- Trillium は 1 epoch ≒ 6MB。`HISTORY` を増やすと転送量がそのまま増える（他所の公開 API）。
  epoch 番号だけなら `/api/epochs` が 52 バイトで済む
- ダッシュボードを追加したら `tests/fixtures/<slug>.json` も足し、`tests/test_build.py` の
  `FIXTURES` に登録する。忘れるとテストと CI が本番 API を叩きにいく
- ロゴを `docs/assets/logos/` に同期してよいのは criteria-miss だけ。`sync_logos()` は対象外の
  ファイルを消すので、他のダッシュボードは読むだけの `available_logos()` を使う
- ディレクトリ構成と各ファイルの役割は `README.md` を参照
