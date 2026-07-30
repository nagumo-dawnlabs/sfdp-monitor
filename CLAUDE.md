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
- 集計ロジックは `dashboards/criteria_miss.py` の `aggregate()` と
  `templates/assets/criteria_miss.js` の `aggregate()` の二重実装。片方を変えたら必ず両方直す
- ディレクトリ構成と各ファイルの役割は `README.md` を参照
