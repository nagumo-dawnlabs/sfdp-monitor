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
  const SLOW_MS = DATA.slow_ms; // 「遅い」の目安。Python 側と 1 か所で共有する

  const PAGE_SIZE = 50; // 初期表示の行数。残りは「Show all」で開く
  const LOGO_DIR = '../assets/logos/'; // criteria-miss が取り込んだものに相乗り（外部リクエストなし）
  const NOISY_BLOCKS = 32; // これ未満のブロック数だと数値が epoch ごとに大きく振れる

  /* スパークラインの縦軸 (ms)。全バリデータで同じ範囲に固定しないと高さが比較できない。
     棒が高い = 遅い = 悪い。実データがだいたい 350-455ms に収まるのでこの範囲 */
  const SPARK_MIN = 350;
  const SPARK_MAX = 460;

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

  /* median slot time は「低いほど良い」ので向きが逆。
   * dashboards/ibrl_criteria.py の MS_TIERS / ms_class() と同じ値。
   * 400ms は IBRL の方法論が「継続スロットなら満点」としている許容値。 */
  const MS_TIERS = [
    [400, 'v-hi'],
    [420, 'v-good'],
    [440, 'v-mid'],
    [470, 'v-low'],
  ];

  function msClass(ms) {
    for (const [max, cls] of MS_TIERS) if (ms <= max) return cls;
    return 'v-bad';
  }

  /* 403.0 -> "403"、420.5 -> "420.5" */
  function ms(value) {
    return value.toFixed(1).replace(/\.0$/, '');
  }

  /* ---- 集計 -------------------------------------------------------------
   * dashboards/ibrl_criteria.py の summarize() と同一アルゴリズム。
   * 片方を変えたら必ずもう片方も変えること（tests/test_ibrl.py が Python 側を固定）。
   *
   * history は「新しい epoch が先頭」の median slot time 列 (ms)。記録の無い
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
    // 前 epoch との差。API 側の増減は IBRL スコアのものなので使わず、履歴から出す
    const prev = v.h.length > 1 ? v.h[1] : null;
    return {
      name: v.n || '(no name)',
      rawName: v.n || '',
      pk: v.p,
      state: v.t,
      stake: v.k,
      fdn: v.f,
      client: v.c || '',
      version: v.cv || '',
      slot: v.b,
      vote: v.v,
      nonvote: v.nv,
      ms: v.m,
      blocks: v.bp,
      delta: prev === null || prev === undefined ? null : v.m - prev,
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
    const min = parseFloat(el('slowerthan').value);
    const floor = isNaN(min) ? -Infinity : min;
    const client = el('client').value;
    return pool().filter(
      (r) =>
        r.ms >= floor &&
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
  /* IBRL の内訳スコア列。主軸ではないので補助扱いだが、向きはスコアのまま
     （昇順 = 悪い順）。IBRL 側に行が無いバリデータは null になりうる */
  const score = (key, label, title) => ({
    key,
    label,
    title,
    cls: 'num',
    right: true,
    value: (r) => (r[key] === null ? Infinity : r[key]),
    cell: (r) => (r[key] === null ? '–' : `<span class="${scoreClass(r[key])}">${r[key].toFixed(1)}</span>`),
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
      key: 'ms',
      label: 'Slot time',
      title: `Median slot time for epoch ${EPOCH} (lower is better)`,
      cls: 'rate',
      right: true,
      desc: true, // 遅い順。このページは遅れている先を探すためのもの
      cell: (r) => `<span class="${msClass(r.ms)}">${ms(r.ms)}</span><span class="unit">ms</span>`,
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
      title: `Mean median slot time over the last ${HISTORY} epochs, skipping epochs with no record`,
      cls: 'num',
      right: true,
      desc: true,
      cell: (r) => (r.sampled ? `<span class="${msClass(r.avg)}">${ms(r.avg)}</span>` : '–'),
    },
    {
      key: 'delta',
      label: 'Δ',
      title: 'Change in median slot time from the previous epoch. Positive means it got slower',
      cls: 'num',
      right: true,
      desc: true, // 悪化幅の大きい順
      // 前 epoch が無い行は並べ替えでも最後に回す
      value: (r) => (r.delta === null ? -Infinity : r.delta),
      cell: (r) => {
        if (r.delta === null) return '<span class="d-flat">–</span>';
        // 遅くなった = 悪い。スコアと違って符号の意味が逆になる
        const cls = r.delta > 0.5 ? 'd-down' : r.delta < -0.5 ? 'd-up' : 'd-flat';
        const sign = r.delta > 0 ? '+' : '';
        return `<span class="${cls}">${sign}${ms(r.delta)}</span>`;
      },
    },
    score('slot', 'Slot score', 'Slot Time Score from IBRL — rewards fast block builds'),
    score('vote', 'Vote pack', 'Vote Packing Score from IBRL — rewards processing votes early in the block'),
    score('nonvote', 'Non-vote', 'Non-Vote Packing Score from IBRL — rewards spreading compute evenly'),
    {
      key: 'blocks',
      label: 'Blocks',
      title: 'Blocks produced in this epoch. A median over very few blocks is noisy',
      cls: 'num',
      right: true,
      desc: true,
      cell: (r) => fmt(r.blocks),
    },
    {
      key: 'spark',
      label: 'Trend',
      title: `Median slot time over the last ${HISTORY} epochs, newest on the left. Taller means slower`,
      sortable: false,
      cell: (r) =>
        `<div class="sparkbar">${r.hist
          .map((v, i) => {
            const epoch = EPOCH - i;
            if (v === null || v === undefined) return `<i class="b-x" title="epoch ${epoch}: no record"></i>`;
            // 高さは所要時間そのもの。高い棒 = 遅い = 悪い（色も同じ向き）
            const pct = Math.max(6, Math.min(100, ((v - SPARK_MIN) / (SPARK_MAX - SPARK_MIN)) * 100));
            return `<i class="${msClass(v)}" style="height:${pct.toFixed(0)}%" title="epoch ${epoch}: ${ms(v)} ms"></i>`;
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
    sortKey: 'ms', // 主軸。列側の desc により既定は降順（遅い順）
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
    const med = median(p.map((r) => r.ms));
    const slow = p.filter((r) => r.ms > SLOW_MS).length;

    DL.renderStats('stats', [
      [fmt(p.length), 'validators measured'],
      [`${ms(med)} ms`, 'median slot time'],
      [fmt(slow), `slower than ${ms(SLOW_MS)} ms`],
      [`${ms(NETWORK.slot_ms)} ms`, 'network median'],
    ]);
    table.render();
  }

  const num = (v, digits) => (v === null || v === undefined ? '' : v.toFixed(digits));

  function downloadCsv() {
    DL.downloadCsv(
      `sfdp_slot_time_e${EPOCH}.csv`,
      [
        'rank',
        'name',
        'pubkey',
        'participant_state',
        'client',
        'client_version',
        'slot_duration_median_ms',
        `avg_slot_duration_median_ms_${HISTORY}_epochs`,
        'epochs_sampled',
        'slot_duration_delta_ms',
        'slot_time_score',
        'vote_packing_score',
        'non_vote_packing_score',
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
        num(r.ms, 1),
        r.sampled ? num(r.avg, 1) : '',
        r.sampled,
        num(r.delta, 1),
        num(r.slot, 2),
        num(r.vote, 2),
        num(r.nonvote, 2),
        r.blocks,
        Math.round(r.stake),
        Math.round(r.fdn),
        EPOCH,
      ]),
    );
  }

  el('q').oninput = render;
  el('slowerthan').oninput = render;
  el('minblocks').onchange = render;
  el('client').onchange = render;
  el('dl').onclick = downloadCsv;

  DL.renderFreshness('freshage', '.freshness time');
  fillClientFilter();
  render();
})();
