/* SFDP Criteria Miss Rate ダッシュボードのページ固有ロジック。
 * 共通のテーブル/CSV/KPI 描画は table.js (DL) が持つ。
 *
 * DATA は base テンプレートが埋め込む docs/data/criteria-miss.json と同じ内容。
 */
(() => {
  const { el, fmt, esc, rateClass } = DL;

  const VALIDATORS = DATA.validators;
  const END_EPOCH = DATA.window.end;
  const HISTORY = DATA.window.history;

  // 埋め込み履歴が短い場合はプリセットが重複するので畳む
  const PRESETS = [...new Set([30, 64, HISTORY].filter((v) => v <= HISTORY))].sort((a, b) => a - b);
  const SPARK_MAX = 40; // 描画するセルの上限。これより長い窓は直近分だけ見せる
  const LOGO_DIR = '../assets/logos/'; // ロゴは同居配信（外部リクエストなし）

  let win = Math.min(64, HISTORY);

  /* ---- 集計 -------------------------------------------------------------
   * dashboards/criteria_miss.py の aggregate() と同一アルゴリズム。
   * 片方を変えたら必ずもう片方も変えること（tests/test_aggregate.py が Python 側を固定）。
   *
   * states は「新しい epoch が先頭」の 1 文字コード列。
   * データ無し ('-') は分母から外すが、連続ミス (streak) は途切れさせない。
   */
  function aggregate(states, window) {
    const s = states.slice(0, window);
    let bonus = 0,
      baseline = 0,
      none = 0,
      party = 0,
      missing = 0,
      streak = 0,
      streakOpen = true;
    for (const c of s) {
      if (c === 'B') bonus++;
      else if (c === 'L') baseline++;
      else if (c === 'N') none++;
      else if (c === 'H') party++;
      else missing++;
      if (c === 'N' && streakOpen) streak++;
      else if (c !== '-') streakOpen = false;
    }
    const evaluated = s.length - missing;
    return {
      bonus,
      baseline,
      none,
      party,
      missing,
      evaluated,
      streak,
      rate: evaluated ? (100 * none) / evaluated : 0,
      nb: evaluated ? (100 * (none + baseline)) / evaluated : 0,
    };
  }

  function computeAll(window) {
    return VALIDATORS.map((v) => ({
      name: v.n || '(no name)',
      rawName: v.n || '',
      pk: v.p,
      state: v.t,
      stake: v.k,
      fdn: v.f,
      // i が立っているバリデータだけロゴファイルが存在する（build 時に同期済み）
      logo: v.i ? `${LOGO_DIR}${v.p}.webp` : '',
      s: v.s.slice(0, window),
      ...aggregate(v.s, window),
    }));
  }

  /* ---- フィルタ ---------------------------------------------------------- */

  function minEvaluated() {
    return el('minev').checked ? Math.max(1, Math.ceil(win / 2)) : 1;
  }

  /* 統計カードの母数。検索やしきい値の絞り込みを受けない「窓全体の姿」を出す */
  function pool() {
    const minEv = minEvaluated();
    return computeAll(win).filter((r) => r.evaluated >= minEv);
  }

  function visible() {
    const q = el('q').value.trim().toLowerCase();
    const minRate = parseFloat(el('minrate').value) || 0;
    return pool().filter(
      (r) => r.rate >= minRate && (!q || r.name.toLowerCase().includes(q) || r.pk.toLowerCase().includes(q)),
    );
  }

  /* ---- 列定義 ------------------------------------------------------------ */

  const COLS = [
    { key: 'rank', label: '#', cls: 'rank', right: true, sortable: false, cell: (r, i) => i + 1 },
    {
      key: 'name',
      label: 'Validator',
      cls: 'name',
      cell: (r) =>
        `<div class="idcell">${DL.avatar(r.rawName, r.logo, r.pk)}<div class="idtext">` +
        `<a href="https://solana.org/sfdp-validators/${r.pk}" target="_blank" rel="noopener" ` +
        `title="${esc(r.name)}">${esc(r.name)}</a>` +
        `<div class="pk">${r.pk.slice(0, 8)}…${r.pk.slice(-6)}</div></div></div>`,
    },
    {
      key: 'rate',
      label: 'Miss rate',
      cls: 'rate',
      right: true,
      desc: true,
      cell: (r) => `<span class="${rateClass(r.rate)}">${r.rate.toFixed(1)}%</span>`,
    },
    {
      key: 'unmet',
      label: 'Missed / rated',
      cls: 'num',
      right: true,
      desc: true,
      value: (r) => r.none,
      cell: (r) => `${r.none} / ${r.evaluated}`,
    },
    { key: 'nb', label: 'not_bonus rate', cls: 'num', right: true, desc: true, cell: (r) => `${r.nb.toFixed(1)}%` },
    { key: 'streak', label: 'Streak', cls: 'num', right: true, desc: true, cell: (r) => r.streak || '–' },
    { key: 'stake', label: 'Stake (SOL)', cls: 'num', right: true, desc: true, cell: (r) => fmt(Math.round(r.stake)) },
    {
      key: 'fdn',
      label: 'SFDP stake',
      cls: 'num',
      right: true,
      desc: true,
      cell: (r) => (r.fdn ? fmt(Math.round(r.fdn)) : '–'),
    },
    {
      key: 'spark',
      label: 'Trend (newest → oldest)',
      sortable: false,
      cell: (r) =>
        `<div class="spark">${[...r.s.slice(0, SPARK_MAX)]
          .map((c, i) => `<i class="s-${c === '-' ? 'x' : c}" title="epoch ${END_EPOCH - i}"></i>`)
          .join('')}</div>`,
    },
  ];

  const table = new DL.SortableTable({
    head: 'head',
    body: 'body',
    empty: 'empty',
    count: 'count',
    cols: COLS,
    sortKey: 'rate',
    rows: visible,
  });
  table.countLabel = (out) => `${fmt(out.length)} shown · epochs ${END_EPOCH - win + 1}–${END_EPOCH}`;

  /* ---- 描画 -------------------------------------------------------------- */

  function render() {
    const p = pool();
    const flagged = p.filter((r) => r.none > 0).length;
    const totalNone = p.reduce((s, r) => s + r.none, 0);
    const totalEval = p.reduce((s, r) => s + r.evaluated, 0);

    DL.renderStats('stats', [
      [`Last ${win}`, 'epoch window'],
      [fmt(p.length), 'validators'],
      [fmt(flagged), 'missed ≥ 1 epoch'],
      [fmt(p.length - flagged), 'clean record'],
      [(totalEval ? (100 * totalNone) / totalEval : 0).toFixed(2) + '%', 'aggregate miss rate'],
    ]);
    table.render();
  }

  function setWindow(n) {
    win = n;
    DL.renderSegment('winseg', PRESETS, win, pickPreset);
    render();
  }

  /* プリセットを押したら「Custom」欄はクリアして、どちらが効いているか一目で分かるようにする */
  function pickPreset(n) {
    el('custom').value = '';
    setWindow(n);
  }

  function downloadCsv() {
    const start = END_EPOCH - win + 1;
    DL.downloadCsv(
      `sfdp_miss_rate_e${start}-${END_EPOCH}.csv`,
      [
        'rank',
        'name',
        'pubkey',
        'participant_state',
        'miss_rate_pct',
        'missed',
        'rated',
        'no_data',
        'not_bonus_rate_pct',
        'current_streak',
        'bonus',
        'baseline',
        'none',
        'none_high_third_party_stake',
        'activated_stake_sol',
        'sfdp_stake_sol',
        'window_start_epoch',
        'window_end_epoch',
      ],
      table.sorted().map((r, i) => [
        i + 1,
        r.name,
        r.pk,
        r.state,
        r.rate.toFixed(2),
        r.none,
        r.evaluated,
        r.missing,
        r.nb.toFixed(2),
        r.streak,
        r.bonus,
        r.baseline,
        r.none,
        r.party,
        Math.round(r.stake),
        Math.round(r.fdn),
        start,
        END_EPOCH,
      ]),
    );
  }

  el('q').oninput = render;
  el('minrate').oninput = render;
  el('minev').onchange = render;
  el('custom').oninput = (e) => {
    const v = parseInt(e.target.value, 10);
    if (v >= 1 && v <= HISTORY) setWindow(v);
  };
  el('dl').onclick = downloadCsv;

  DL.renderFreshness('freshage', '.freshness time');
  setWindow(win);
})();
