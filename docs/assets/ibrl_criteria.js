/* IBRL Criteria ダッシュボードのページ固有ロジック。
 * 共通のテーブル/CSV/KPI 描画は table.js (DL) が持つ。
 *
 * DATA は base テンプレートが埋め込む docs/data/ibrl-criteria.json と同じ内容。
 */
(() => {
  const { el, fmt, esc } = DL;

  const VALIDATORS = DATA.validators;
  const EPOCH = DATA.epoch;
  const HISTORY = DATA.history;
  const NETWORK = DATA.network;

  const PAGE_SIZE = 50; // 初期表示の行数。残りは「Show all」で開く
  const LOGO_DIR = '../assets/logos/'; // criteria-miss が取り込んだものに相乗り（外部リクエストなし）
  const NOISY_BLOCKS = 32; // これ未満のブロック数だとスコアが epoch ごとに大きく振れる

  /* スパークラインの縦軸。全バリデータで同じ範囲に固定しないと高さが比較できない */
  const SPARK_MIN = 50;
  const SPARK_MAX = 100;

  /* ---- スコアの色分け ----------------------------------------------------
   * dashboards/ibrl_criteria.py の SCORE_TIERS / score_class() と同じ値。
   * 率と違って「高いほど良い」ので table.js の rateClass は使わない。
   */
  const SCORE_TIERS = [
    [95, 'v-hi'], // 緑
    [90, 'v-good'], // 既定色
    [80, 'v-mid'], // 黄
    [70, 'v-low'], // オレンジ
  ];

  function scoreClass(score) {
    for (const [min, cls] of SCORE_TIERS) if (score >= min) return cls;
    return 'v-bad';
  }

  /* Median Block Build は「低いほど良い」ので別のしきい値を持つ */
  function msClass(ms) {
    if (ms <= 380) return 'v-hi';
    if (ms <= 430) return 'v-good';
    if (ms <= 500) return 'v-mid';
    return 'v-low';
  }

  /* ---- 集計 -------------------------------------------------------------
   * dashboards/ibrl_criteria.py の summarize() と同一アルゴリズム。
   * 片方を変えたら必ずもう片方も変えること（tests/test_ibrl.py が Python 側を固定）。
   *
   * history は「新しい epoch が先頭」の IBRL スコア列。ブロックを作っていない
   * epoch は null で入っているので、平均の分母から外す。
   */
  function summarize(history) {
    let sum = 0;
    let sampled = 0;
    for (const v of history) {
      if (v === null || v === undefined) continue;
      sum += v;
      sampled++;
    }
    return { average: sampled ? sum / sampled : 0, sampled };
  }

  const ROWS = VALIDATORS.map((v) => {
    const { average, sampled } = summarize(v.h);
    return {
      name: v.n || '(no name)',
      rawName: v.n || '',
      pk: v.p,
      state: v.t,
      stake: v.k,
      fdn: v.f,
      ibrl: v.i,
      client: v.c || '',
      version: v.cv || '',
      slot: v.b,
      vote: v.v,
      nonvote: v.nv,
      ms: v.m,
      blocks: v.bp,
      delta: v.tr,
      hist: v.h,
      avg: average,
      sampled,
      // lg が立っているバリデータだけロゴファイルが存在する
      logo: v.lg ? `${LOGO_DIR}${v.p}.webp` : '',
    };
  });

  /* ---- フィルタ ---------------------------------------------------------- */

  /* 統計カードの母数。検索は受けないが、ノイズ除外の切り替えは反映する
     （「今この表が何を母数にしているか」と KPI をずらさないため） */
  function pool() {
    return el('minblocks').checked ? ROWS.filter((r) => r.blocks >= NOISY_BLOCKS) : ROWS;
  }

  function visible() {
    const q = el('q').value.trim().toLowerCase();
    const max = parseFloat(el('maxscore').value);
    const cap = isNaN(max) ? Infinity : max;
    const client = el('client').value;
    return pool().filter(
      (r) =>
        r.ibrl <= cap &&
        (!client || r.client === client) &&
        (!q || r.name.toLowerCase().includes(q) || r.pk.toLowerCase().includes(q)),
    );
  }

  /* クライアントの絞り込み。多い順に並べ、件数を添えて分布そのものも読めるようにする */
  function fillClientFilter() {
    const counts = new Map();
    for (const r of ROWS) counts.set(r.client, (counts.get(r.client) || 0) + 1);
    const opts = [...counts.entries()]
      .filter(([name]) => name)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([name, n]) => `<option value="${esc(name)}">${esc(name)} (${n})</option>`)
      .join('');
    el('client').innerHTML = `<option value="">All clients</option>${opts}`;
  }

  /* ---- 列定義 ------------------------------------------------------------ */

  /* スコア列は昇順（悪い順）から始める。このページは「下がっている先」を探すためのもので、
     満点付近が 50 行続く画面には用が無い。desc を立てないので初期表示もクリック後も同じ向き */
  const score = (key, label, title) => ({
    key,
    label,
    title,
    cls: 'num',
    right: true,
    cell: (r) => `<span class="${scoreClass(r[key])}">${r[key].toFixed(1)}</span>`,
  });

  const COLS = [
    { key: 'rank', label: '#', cls: 'rank', right: true, sortable: false, cell: (r, i) => i + 1 },
    {
      key: 'name',
      label: 'Validator',
      cls: 'name',
      cell: (r) =>
        `<div class="idcell">${DL.avatar(r.rawName, r.logo, r.pk)}<div class="idtext">` +
        `<a href="https://ibrl.wtf/validator/${r.pk}/" target="_blank" rel="noopener" ` +
        `title="${esc(r.name)}">${esc(r.name)}</a>` +
        `<div class="pk">${r.pk.slice(0, 8)}…${r.pk.slice(-6)}</div></div></div>`,
    },
    {
      key: 'ibrl',
      label: 'IBRL',
      title: `IBRL score for epoch ${EPOCH}`,
      cls: 'rate',
      right: true,
      cell: (r) => `<span class="${scoreClass(r.ibrl)}">${r.ibrl.toFixed(1)}</span>`,
    },
    {
      key: 'client',
      label: 'Client',
      title: 'Validator client reported over gossip, and its version',
      cls: 'client',
      // 名前が同じときはバージョンで並ぶようにしておくと、版の遅れが固まって見える
      value: (r) => `${r.client || '￿'} ${r.version}`,
      cell: (r) =>
        r.client
          ? `<span class="cname">${esc(r.client)}</span>` +
            (r.version ? `<span class="cver">${esc(r.version)}</span>` : '')
          : '<span class="cver">unknown</span>',
    },
    {
      key: 'avg',
      label: `Avg ${HISTORY}e`,
      title: `Mean IBRL score over the last ${HISTORY} epochs, skipping epochs with no blocks`,
      cls: 'num',
      right: true,
      cell: (r) => (r.sampled ? `<span class="${scoreClass(r.avg)}">${r.avg.toFixed(1)}</span>` : '–'),
    },
    {
      key: 'delta',
      label: 'Δ',
      title: 'Change in IBRL score from the previous epoch',
      cls: 'num',
      right: true,
      desc: true,
      cell: (r) => {
        const cls = r.delta > 0.05 ? 'd-up' : r.delta < -0.05 ? 'd-down' : 'd-flat';
        const sign = r.delta > 0 ? '+' : '';
        return `<span class="${cls}">${sign}${r.delta.toFixed(1)}</span>`;
      },
    },
    score('slot', 'Slot time', 'Slot Time Score — 40% of IBRL. Rewards fast block builds'),
    score('vote', 'Vote pack', 'Vote Packing Score — 15% of IBRL. Rewards processing votes early in the block'),
    score('nonvote', 'Non-vote', 'Non-Vote Packing Score — 45% of IBRL. Rewards spreading compute evenly'),
    {
      key: 'ms',
      label: 'Build',
      title: 'Median block build time in this epoch (lower is better)',
      cls: 'num',
      right: true,
      desc: true,
      cell: (r) => `<span class="${msClass(r.ms)}">${fmt(r.ms)}</span><span class="unit">ms</span>`,
    },
    {
      key: 'blocks',
      label: 'Blocks',
      title: 'Blocks produced in this epoch. A score from very few blocks is noisy',
      cls: 'num',
      right: true,
      desc: true,
      cell: (r) => fmt(r.blocks),
    },
    {
      key: 'spark',
      label: 'Trend',
      title: `IBRL score over the last ${HISTORY} epochs, newest on the left`,
      sortable: false,
      cell: (r) =>
        `<div class="sparkbar">${r.hist
          .map((v, i) => {
            const epoch = EPOCH - i;
            if (v === null || v === undefined) return `<i class="b-x" title="epoch ${epoch}: no blocks"></i>`;
            const pct = Math.max(6, Math.min(100, ((v - SPARK_MIN) / (SPARK_MAX - SPARK_MIN)) * 100));
            return `<i class="${scoreClass(v)}" style="height:${pct.toFixed(0)}%" title="epoch ${epoch}: ${v.toFixed(1)}"></i>`;
          })
          .join('')}</div>`,
    },
  ];

  const table = new DL.SortableTable({
    head: 'head',
    body: 'body',
    empty: 'empty',
    count: 'count',
    more: 'more',
    pageSize: PAGE_SIZE,
    cols: COLS,
    sortKey: 'ibrl',
    rows: visible,
  });
  table.countLabel = (shown, all) =>
    `${shown.length < all.length ? `${fmt(shown.length)} of ${fmt(all.length)}` : fmt(all.length)} · epoch ${EPOCH}`;

  /* ---- 描画 -------------------------------------------------------------- */

  function median(values) {
    if (!values.length) return 0;
    const s = [...values].sort((a, b) => a - b);
    const mid = s.length >> 1;
    return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
  }

  function render() {
    const p = pool();
    const med = median(p.map((r) => r.ibrl));
    const below = p.filter((r) => r.ibrl < 85).length;

    DL.renderStats('stats', [
      [fmt(p.length), 'validators scored'],
      [med.toFixed(1), 'median IBRL score'],
      [fmt(below), 'scoring below 85'],
      [NETWORK.ibrl_score.toFixed(1), 'network average'],
    ]);
    table.render();
  }

  function downloadCsv() {
    DL.downloadCsv(
      `sfdp_ibrl_e${EPOCH}.csv`,
      [
        'rank',
        'name',
        'pubkey',
        'participant_state',
        'client',
        'client_version',
        'ibrl_score',
        `avg_ibrl_${HISTORY}_epochs`,
        'epochs_sampled',
        'epoch_delta',
        'slot_time_score',
        'vote_packing_score',
        'non_vote_packing_score',
        'median_block_build_ms',
        'blocks_produced',
        'activated_stake_sol',
        'sfdp_stake_sol',
        'epoch',
      ],
      table.sorted().map((r, i) => [
        i + 1,
        r.name,
        r.pk,
        r.state,
        r.client,
        r.version,
        r.ibrl.toFixed(2),
        r.sampled ? r.avg.toFixed(2) : '',
        r.sampled,
        r.delta.toFixed(2),
        r.slot.toFixed(2),
        r.vote.toFixed(2),
        r.nonvote.toFixed(2),
        r.ms,
        r.blocks,
        Math.round(r.stake),
        Math.round(r.fdn),
        EPOCH,
      ]),
    );
  }

  el('q').oninput = render;
  el('maxscore').oninput = render;
  el('minblocks').onchange = render;
  el('client').onchange = render;
  el('dl').onclick = downloadCsv;

  DL.renderFreshness('freshage', '.freshness time');
  fillClientFilter();
  render();
})();
