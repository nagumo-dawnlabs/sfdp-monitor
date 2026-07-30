/* 全ダッシュボード共通のテーブル基盤。
 *
 * ページ固有のコードは「列の定義」と「行データの作り方」だけを書けばよく、
 * ソート・見出しの描画・空表示・CSV 書き出しはここが持つ。
 * ES モジュールにしていないのは file:// で開いたときに CORS で死ぬのを避けるため。
 */
const DL = (() => {
  const el = (id) => document.getElementById(id);
  const fmt = (n) => Number(n).toLocaleString('en-US');

  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);

  /* 率に応じた色クラス。tiers は [しきい値, クラス] を降順に並べたもの */
  const RATE_TIERS = [
    [20, 'r-hi'], // 赤
    [15, 'r-orange'], // オレンジ
    [10, 'r-mid'], // 黄
  ];

  function rateClass(rate, tiers = RATE_TIERS) {
    if (rate === 0) return 'r-zero';
    for (const [min, cls] of tiers) if (rate >= min) return cls;
    return 'r-lo';
  }

  /* 「Data as of」の横に相対時間を出す。JS が無効でも絶対時刻は HTML 側に出ている */
  function renderFreshness(ageId, timeSelector) {
    const t = document.querySelector(timeSelector);
    const age = el(ageId);
    if (!t || !age) return;
    const then = new Date(t.getAttribute('datetime'));
    if (isNaN(then)) return;
    const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
    const days = Math.floor(mins / 1440);
    const hours = Math.floor(mins / 60);
    let rel;
    if (mins < 2) rel = 'just now';
    else if (mins < 60) rel = `${mins} minutes ago`;
    else if (hours < 24) rel = `${hours} hour${hours === 1 ? '' : 's'} ago`;
    else rel = `${days} day${days === 1 ? '' : 's'} ago`;
    // 前後に空白を入れて、コピーや読み上げでも文として成立させる
    age.textContent = ` · updated ${rel}`;
  }

  /* ロゴがあれば画像、無ければ名前の頭文字。地色は seed（pubkey）から決めるので
     名前が変わっても同じバリデータの色は変わらない。
     画像は同居配信（docs/assets/logos/）なので外部リクエストは発生しない。 */
  function avatar(name, logoPath, seed) {
    if (logoPath) {
      return (
        `<span class="avatar"><img src="${logoPath}" alt="" loading="lazy" decoding="async" ` +
        `width="28" height="28"></span>`
      );
    }
    // 記号で始まる名前でも意味のある 1 文字になるよう、先頭の英数字を採る
    const label = (String(name).match(/[\p{L}\p{N}]/u)?.[0] || '?').toUpperCase();
    const hue = [...String(seed || name)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
    return `<span class="avatar initial" style="background:hsl(${hue} 45% 26%)">${esc(label)}</span>`;
  }

  /* cols の各要素:
   *   key       ソートキー兼識別子
   *   label     見出し文字列
   *   title     見出しの tooltip（略した見出しの補足）
   *   cls       td に付けるクラス（見た目を持つので th とは共有しない）
   *   right     true なら見出しも右寄せ（数値列向け）
   *   desc      true なら初回クリックで降順（数値列向け）
   *   sortable  false で固定列（# など）
   *   value(r)  ソートに使う値。既定は r[key]
   *   cell(r,i) セルの innerHTML。i は表示順（0 起点）
   *
   * pageSize / more: 初期表示を先頭 pageSize 行に切り、残りは more ボタンで開く。
   * 数百行を一度に描くと縦に延々と続いて読めなくなるため、既定は「上位だけ」。
   * CSV とソートは常に全行が対象（sorted() は切らない）。
   */
  class SortableTable {
    constructor({ head, body, empty, count, cols, sortKey, rows, pageSize, more }) {
      this.head = el(head);
      this.body = el(body);
      this.empty = empty ? el(empty) : null;
      this.count = count ? el(count) : null;
      this.cols = cols;
      this.sortKey = sortKey;
      this.sortDir = this._colOf(sortKey)?.desc ? -1 : 1;
      this.rows = rows; // () => 表示対象の行配列を返す
      this.countLabel = null; // () => 件数欄に出す文字列
      this.pageSize = pageSize || 0; // 0 なら制限なし
      this.limit = this.pageSize;
      this.more = more ? el(more) : null;
      if (this.more) {
        // 一度「全件」を選んだらそのまま。ソートやフィルタのたびに畳み直さない
        this.more.onclick = () => {
          this.limit = 0;
          this.render();
        };
      }
      this._renderHead();
    }

    _colOf(key) {
      return this.cols.find((c) => c.key === key);
    }

    _renderHead() {
      this.head.innerHTML = this.cols
        .map((c) => {
          const active = this.sortKey === c.key;
          const cls = c.right ? ' class="th-r"' : '';
          const tip = c.title ? ` title="${esc(c.title)}"` : '';
          if (c.sortable === false) return `<th${cls}><span class="static"${tip}>${c.label}</span></th>`;
          const arrow = active ? (this.sortDir === -1 ? '↓' : '↑') : '↕';
          const sort = active ? ` aria-sort="${this.sortDir === -1 ? 'descending' : 'ascending'}"` : '';
          return (
            `<th${cls}${sort}>` +
            `<button type="button" class="sort" data-key="${c.key}"${tip}>` +
            `${c.label}<span class="arrow" aria-hidden="true">${arrow}</span></button></th>`
          );
        })
        .join('');
      this.head.querySelectorAll('button.sort').forEach((b) => {
        b.onclick = () => this.sortBy(b.dataset.key);
      });
    }

    sortBy(key) {
      if (this.sortKey === key) this.sortDir = -this.sortDir;
      else {
        this.sortKey = key;
        this.sortDir = this._colOf(key).desc ? -1 : 1;
      }
      this._renderHead();
      this.render();
    }

    /* ソート済みの行。CSV 書き出しも同じ順序を使う */
    sorted() {
      const col = this._colOf(this.sortKey);
      const val = col.value || ((r) => r[col.key]);
      const dir = this.sortDir;
      return this.rows().sort((a, b) => {
        const x = val(a);
        const y = val(b);
        if (typeof x === 'string' || typeof y === 'string') {
          const cmp = String(x).toLowerCase().localeCompare(String(y).toLowerCase());
          if (cmp) return cmp * dir;
        } else if (x !== y) {
          return (x - y) * dir;
        }
        // 同値のときは名前で安定させる
        return String(a.name ?? '').toLowerCase() < String(b.name ?? '').toLowerCase() ? -1 : 1;
      });
    }

    render() {
      const out = this.sorted();
      const shown = this.limit ? out.slice(0, this.limit) : out;
      this.body.innerHTML = shown
        .map((r, i) => `<tr>${this.cols.map((c) => `<td class="${c.cls || ''}">${c.cell(r, i)}</td>`).join('')}</tr>`)
        .join('');
      if (this.empty) this.empty.hidden = out.length > 0;
      if (this.more) {
        this.more.hidden = shown.length >= out.length;
        this.more.textContent = `Show all ${fmt(out.length)}`;
      }
      if (this.count && this.countLabel) this.count.textContent = this.countLabel(shown, out);
      return out;
    }
  }

  /* KPI カードを描画する */
  function renderStats(id, pairs) {
    el(id).innerHTML = pairs
      .map(([v, k]) => `<div class="stat"><div class="v">${v}</div><div class="k">${k}</div></div>`)
      .join('');
  }

  /* 数値プリセットの切り替えボタン列 */
  function renderSegment(id, values, current, onPick) {
    const box = el(id);
    box.innerHTML = values.map((v) => `<button type="button" data-v="${v}" aria-pressed="${v === current}">${v}</button>`).join('');
    box.querySelectorAll('button').forEach((b) => {
      b.onclick = () => onPick(Number(b.dataset.v));
    });
  }

  /* Excel が UTF-8 と判別できるよう BOM を付ける。
     引用符は区切り文字・引用符・改行を含む値だけに付ける（数値をそのまま数値として読ませる） */
  function downloadCsv(filename, header, records) {
    const q = (v) => {
      const s = String(v);
      return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [header.join(',')].concat(records.map((r) => r.map(q).join(',')));
    const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return {
    el,
    fmt,
    esc,
    avatar,
    rateClass,
    RATE_TIERS,
    renderFreshness,
    SortableTable,
    renderStats,
    renderSegment,
    downloadCsv,
  };
})();
