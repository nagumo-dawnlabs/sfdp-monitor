#!/usr/bin/env python3
"""SFDP 基準未達率の公開用ダッシュボード (docs/index.html) を生成する。

直近 HISTORY epoch 分の state を 1 文字コードの文字列として埋め込み、
集計期間 (直近 X epoch) の切り替え・ソート・フィルタはすべてブラウザ側で行う。
外部依存ゼロの単一 HTML なので GitHub Pages にそのまま置ける。

    python3 build_site.py                # キャッシュを使って生成
    python3 build_site.py --history 128  # 埋め込む epoch 数
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sfdp_status as S

LAMPORTS = 1_000_000_000

# state -> 埋め込み用 1 文字コード
CODE = {
    "Bonus": "B",
    "Baseline": "L",
    "None": "N",
    "NoneHighThirdPartyStake": "H",
}
MISSING = "-"

HTML_TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SFDP 基準未達率ダッシュボード</title>
<meta name="description" content="Solana Foundation Delegation Program 参加バリデータの epoch 別基準達成状況を集計したダッシュボード。">
<style>
:root{
  --bg:#050508; --accent:#ff7300; --accent-hover:#e66800;
  --text:#e8e8ec; --text-2:#6b6b80; --text-muted:#4a4a5a;
  --border:#12121e; --card:rgb(26 26 46 / 30%);
  --ok:#15d27a; --bad:#ff6b6b; --warn:#ffb340; --party:#15d27a;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--text);
  font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  font-size:16px; line-height:1.6; -webkit-font-smoothing:antialiased;
}
body::before{
  content:''; position:fixed; inset:0; pointer-events:none; z-index:0;
  background-image:radial-gradient(circle at 2px 2px, rgb(255 255 255 / 3%) 1px, transparent 0);
  background-size:24px 24px;
}
.wrap{position:relative; z-index:1; max-width:1200px; margin:0 auto; padding:48px 24px 96px}
h1{font-size:clamp(1.75rem,5vw,2.5rem); line-height:1.1; letter-spacing:-0.03em; font-weight:800; margin:0 0 8px}
.lede{color:var(--text-2); max-width:800px; margin:0 0 32px; font-size:1rem}
.lede a{color:var(--accent); text-decoration:none}
.lede a:hover{color:var(--accent-hover); text-decoration:underline}
.stats{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:28px}
.stat{
  background:linear-gradient(135deg,var(--card) 60%, rgb(255 115 0 / 8%));
  backdrop-filter:blur(12px); border:1px solid var(--border);
  border-radius:14px; padding:16px 18px;
}
.stat .v{font-size:1.75rem; font-weight:700; letter-spacing:-0.02em; line-height:1.1}
.stat .k{font-size:0.6875rem; text-transform:uppercase; letter-spacing:0.12em; color:var(--text-muted); margin-top:6px}
.controls{
  background:var(--card); backdrop-filter:blur(12px); border:1px solid var(--border);
  border-radius:14px; padding:18px; margin-bottom:20px;
  display:flex; flex-wrap:wrap; gap:20px; align-items:flex-end;
}
.field{display:flex; flex-direction:column; gap:7px}
.field > label{font-size:0.6875rem; text-transform:uppercase; letter-spacing:0.12em; color:var(--text-muted)}
.seg{display:flex; gap:6px; flex-wrap:wrap}
button.chip,.seg button{
  background:rgb(255 115 0 / 6%); color:var(--text); border:1px solid rgb(255 115 0 / 12%);
  border-radius:999px; padding:6px 14px; font:inherit; font-size:0.875rem; cursor:pointer;
  transition:background .2s ease,border-color .2s ease,color .2s ease;
}
.seg button:hover{background:rgb(255 115 0 / 14%)}
.seg button[aria-pressed=true]{background:rgb(255 115 0 / 38%); border-color:var(--accent); font-weight:600}
input[type=text],input[type=number],select{
  background:rgb(255 255 255 / 4%); color:var(--text); border:1px solid var(--border);
  border-radius:8px; padding:8px 12px; font:inherit; font-size:0.9375rem;
}
input:focus,select:focus{outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgb(255 115 0 / 12%)}
input[type=text]{min-width:230px}
input[type=number]{width:92px}
.check{display:flex; align-items:center; gap:8px; font-size:0.875rem; color:var(--text-2); cursor:pointer}
.check input{accent-color:var(--accent); width:16px; height:16px}
.tablewrap{
  border:1px solid var(--border); border-radius:14px; overflow-x:auto;
  background:rgb(26 26 46 / 20%); backdrop-filter:blur(12px);
}
table{border-collapse:collapse; width:100%; font-size:0.875rem}
thead th{
  position:sticky; top:0; z-index:2; background:#0b0b14; text-align:left; white-space:nowrap;
  font-size:0.6875rem; text-transform:uppercase; letter-spacing:0.1em; color:var(--text-2);
  font-weight:600; padding:12px 14px; border-bottom:1px solid var(--border); cursor:pointer;
  user-select:none; transition:color .2s ease;
}
thead th:hover{color:var(--text)}
thead th[aria-sort]{color:var(--accent)}
thead th .arrow{opacity:.45; margin-left:4px}
tbody td{padding:11px 14px; border-bottom:1px solid rgb(18 18 30 / 70%); vertical-align:middle}
tbody tr:hover{background:rgb(255 115 0 / 4%)}
tbody tr:last-child td{border-bottom:none}
.num{text-align:right; font-family:'SF Mono',Monaco,Inconsolata,'Roboto Mono',monospace; font-variant-numeric:tabular-nums}
.rank{color:var(--text-muted); text-align:right; font-variant-numeric:tabular-nums}
.name a{color:var(--text); text-decoration:none; font-weight:500}
.name a:hover{color:var(--accent)}
.pk{font-family:'SF Mono',Monaco,Inconsolata,'Roboto Mono',monospace; font-size:0.75rem; color:var(--text-muted)}
.rate{font-weight:700; font-variant-numeric:tabular-nums; text-align:right;
  font-family:'SF Mono',Monaco,Inconsolata,'Roboto Mono',monospace}
.r-hi{color:var(--bad)} .r-mid{color:var(--warn)} .r-lo{color:var(--text-2)} .r-zero{color:var(--text-muted)}
.spark{display:flex; gap:2px; min-width:120px}
.spark i{width:7px; height:16px; border-radius:2px; display:block; flex:0 0 auto}
.s-B{background:var(--ok)} .s-N{background:var(--bad)} .s-L{background:var(--warn)}
.s-H{background:var(--party); opacity:.55} .s-x{background:rgb(255 255 255 / 8%)}
.badge{display:inline-block; font-size:0.6875rem; letter-spacing:0.06em; padding:2px 8px; border-radius:999px;
  background:rgb(255 255 255 / 6%); color:var(--text-2)}
.legend{display:flex; flex-wrap:wrap; gap:18px; margin:14px 0 26px; font-size:0.8125rem; color:var(--text-2)}
.legend span{display:flex; align-items:center; gap:7px}
.legend i{width:11px; height:11px; border-radius:3px; display:inline-block}
.meta{display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin:0 0 12px;
  font-size:0.8125rem; color:var(--text-2)}
.empty{padding:56px 24px; text-align:center; color:var(--text-muted)}
footer{margin-top:40px; padding-top:24px; border-top:1px solid var(--border); font-size:0.8125rem; color:var(--text-muted)}
footer a{color:var(--text-2)}
h2{font-size:1.5rem; letter-spacing:-0.02em; margin:44px 0 10px}
.notes{font-size:0.875rem; color:var(--text-2); max-width:800px}
.notes code{background:rgb(255 255 255 / 6%); padding:1px 6px; border-radius:4px; font-size:0.8125rem}
.notes table{font-size:0.8125rem; margin:14px 0; width:auto}
.notes td,.notes th{padding:6px 16px 6px 0; border-bottom:1px solid var(--border); text-align:left}
@media(max-width:768px){
  .wrap{padding:32px 16px 64px}
  .controls{gap:14px}
  input[type=text]{min-width:0; width:100%}
  .field{flex:1 1 100%}
  .spark{display:none}
}
</style>
</head>
<body>
<div class="wrap">
<h1>SFDP 基準未達率</h1>
<p class="lede">
Solana Foundation Delegation Program 参加バリデータが、直近 X epoch のうち何割で
プログラム基準を満たさなかったか（<a href="https://solana.org/sfdp-validators/__SAMPLE__" target="_blank" rel="noopener">solana.org
の各バリデータページ</a>で赤いバツになっている epoch の割合）。
epoch <strong>__START__</strong> – <strong>__END__</strong> のデータを収録。__GENERATED__ 時点。
</p>

<div class="stats" id="stats"></div>

<div class="controls">
  <div class="field">
    <label>集計期間（直近 epoch 数）</label>
    <div class="seg" id="winseg"></div>
  </div>
  <div class="field">
    <label for="custom">任意の epoch 数</label>
    <input type="number" id="custom" min="1" max="__HISTORY__" step="1" placeholder="例 20">
  </div>
  <div class="field">
    <label for="q">名前 / pubkey 検索</label>
    <input type="text" id="q" placeholder="Syndica, mXv18... など" autocomplete="off">
  </div>
  <div class="field">
    <label for="minrate">未達率の下限 (%)</label>
    <input type="number" id="minrate" min="0" max="100" step="1" value="0">
  </div>
  <div class="field">
    <label>表示条件</label>
    <label class="check"><input type="checkbox" id="minev" checked> データが期間の半分以上ある行のみ</label>
  </div>
  <div class="field">
    <label>&nbsp;</label>
    <button class="chip" id="dl">CSV ダウンロード</button>
  </div>
</div>

<div class="legend">
  <span><i class="s-B"></i>Bonus（緑の星 / 基準達成）</span>
  <span><i class="s-L"></i>Baseline（オレンジのチェック / matching 未達）</span>
  <span><i class="s-N"></i>None（赤いバツ / 基準未達）</span>
  <span><i class="s-H"></i>NoneHighThirdPartyStake（緑のクラッカー）</span>
  <span><i class="s-x"></i>データなし（オンボード前 / delinquent）</span>
</div>

<div class="meta"><div id="count"></div><div>列見出しをクリックでソート</div></div>

<div class="tablewrap">
<table>
<thead><tr id="head"></tr></thead>
<tbody id="body"></tbody>
</table>
<div class="empty" id="empty" hidden>条件に合うバリデータがありません</div>
</div>

<h2>判定方法</h2>
<div class="notes">
<p>
solana.org のバリデータページに並ぶ epoch 別アイコンは、Solana Foundation の API が返す
epoch ごとの state と 1:1 で対応する。本ページはその state をそのまま集計している。
</p>
<table>
<tr><th>state</th><th>solana.org のアイコン</th><th>本ページの扱い</th></tr>
<tr><td><code>Bonus</code></td><td>緑の星</td><td>達成</td></tr>
<tr><td><code>Baseline</code></td><td>オレンジのチェック</td><td>未達に数えない（matching 未達・residual 達成のため。not_bonus 率に計上）</td></tr>
<tr><td><code>None</code></td><td>赤いバツ</td><td><strong>未達</strong></td></tr>
<tr><td><code>NoneHighThirdPartyStake</code></td><td>緑のクラッカー</td><td>達成扱い（third party stake が十分で SFDP stake 不要）</td></tr>
</table>
<p>
<strong>未達率</strong> = <code>None</code> の epoch 数 ÷ データのある epoch 数。
<strong>not_bonus 率</strong> = (<code>None</code> + <code>Baseline</code>) ÷ データのある epoch 数。
epoch がマップに存在しない場合はオンボード前または delinquent とみなし、分母から除外する。
新規参加バリデータは母数が小さく率が極端になるため、既定では「データが期間の半分以上ある行」に絞っている。
</p>
</div>

<footer>
データ出典: <a href="https://solana.org/delegation-api-docs" target="_blank" rel="noopener">Solana Foundation Delegation Program API</a>
（<code>sfdp_participants</code> および各バリデータの epoch 別 state）。
対象は participant state = <code>__STATES__</code>、cluster = <code>__CLUSTER__</code>。
本ページは Solana Foundation の公式発表ではなく、公開 API を集計した非公式の資料。
生成元: <a href="__REPO__" target="_blank" rel="noopener">sfdp-monitor</a> by DawnLabs
</footer>
</div>

<script>
const DATA = __DATA__;
const HISTORY = __HISTORY__;
const END_EPOCH = __END__;
const PRESETS = [5, 10, 30, 64, HISTORY];
const SPARK_MAX = 40;  // 描画するマス数の上限（期間がこれより長いと直近分のみ表示）

const COLS = [
  {key:'rank',  label:'#',            cls:'rank', sortable:false},
  {key:'name',  label:'Validator',    cls:'name'},
  {key:'rate',  label:'未達率',        cls:'rate', desc:true},
  {key:'unmet', label:'未達 / 評価',   cls:'num',  desc:true},
  {key:'nb',    label:'not_bonus率',  cls:'num',  desc:true},
  {key:'streak',label:'連続未達',      cls:'num',  desc:true},
  {key:'stake', label:'Stake (SOL)',  cls:'num',  desc:true},
  {key:'fdn',   label:'SFDP stake',   cls:'num',  desc:true},
  {key:'spark', label:'期間内の推移 (新 → 旧)', cls:'spark', sortable:false},
];

let win = 10, sortKey = 'rate', sortDir = -1;

const el = id => document.getElementById(id);
const fmt = n => n.toLocaleString('en-US');

function compute(w) {
  return DATA.map(v => {
    // states は新しい epoch が先頭
    const s = v.s.slice(0, w);
    let bonus = 0, baseline = 0, none = 0, party = 0, missing = 0, streak = 0, streakOpen = true;
    for (const c of s) {
      if (c === 'B') bonus++;
      else if (c === 'L') baseline++;
      else if (c === 'N') none++;
      else if (c === 'H') party++;
      else missing++;
      if (c === 'N' && streakOpen) streak++;
      else if (c !== '-') streakOpen = false;
    }
    const evaluated = w - missing;
    return {
      name: v.n || '(no name)', pk: v.p, state: v.t,
      stake: v.k, fdn: v.f, s,
      bonus, baseline, none, party, missing, evaluated, streak,
      rate: evaluated ? 100 * none / evaluated : 0,
      nb: evaluated ? 100 * (none + baseline) / evaluated : 0,
    };
  });
}

function filtered() {
  const rows = compute(win);
  const q = el('q').value.trim().toLowerCase();
  const minRate = parseFloat(el('minrate').value) || 0;
  const minEv = el('minev').checked ? Math.max(1, Math.ceil(win / 2)) : 1;
  const out = rows.filter(r =>
    r.evaluated >= minEv &&
    r.rate >= minRate &&
    (!q || r.name.toLowerCase().includes(q) || r.pk.toLowerCase().includes(q))
  );
  out.sort((a, b) => {
    let x, y;
    if (sortKey === 'name') { x = a.name.toLowerCase(); y = b.name.toLowerCase(); return x < y ? -sortDir : x > y ? sortDir : 0; }
    if (sortKey === 'unmet') { x = a.none; y = b.none; } else { x = a[sortKey]; y = b[sortKey]; }
    if (x === y) return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1;
    return (x - y) * sortDir;
  });
  return {rows, out, minEv};
}

function rateClass(r) {
  if (r === 0) return 'r-zero';
  if (r >= 50) return 'r-hi';
  if (r >= 10) return 'r-mid';
  return 'r-lo';
}

function renderHead() {
  el('head').innerHTML = COLS.map(c => {
    const active = sortKey === c.key;
    const arrow = c.sortable === false ? '' :
      `<span class="arrow">${active ? (sortDir === -1 ? '\\u2193' : '\\u2191') : '\\u2195'}</span>`;
    const attrs = [`data-key="${c.key}"`];
    if (active) attrs.push(`aria-sort="${sortDir === -1 ? 'descending' : 'ascending'}"`);
    if (c.sortable === false) attrs.push('style="cursor:default"');
    return `<th ${attrs.join(' ')}>${c.label}${arrow}</th>`;
  }).join('');
  el('head').querySelectorAll('th').forEach(th => {
    const key = th.dataset.key;
    if (!key || COLS.find(c => c.key === key).sortable === false) return;
    th.onclick = () => {
      if (sortKey === key) sortDir = -sortDir;
      else { sortKey = key; sortDir = COLS.find(c => c.key === key).desc ? -1 : 1; }
      render();
    };
  });
}

function render() {
  const {rows, out, minEv} = filtered();
  const poolRows = rows.filter(r => r.evaluated >= minEv);
  const pool = poolRows.length;
  const flagged = poolRows.filter(r => r.none > 0).length;
  const perfect = pool - flagged;
  const totalNone = poolRows.reduce((s, r) => s + r.none, 0);
  const totalEval = poolRows.reduce((s, r) => s + r.evaluated, 0);

  el('stats').innerHTML = [
    [`直近 ${win}`, 'EPOCH'],
    [fmt(pool), '対象バリデータ'],
    [fmt(flagged), '未達 1 回以上'],
    [fmt(perfect), '全 epoch 達成'],
    [(totalEval ? 100 * totalNone / totalEval : 0).toFixed(2) + '%', '全体の未達率'],
  ].map(([v, k]) => `<div class="stat"><div class="v">${v}</div><div class="k">${k}</div></div>`).join('');

  el('count').textContent = `${fmt(out.length)} 件を表示 / epoch ${END_EPOCH - win + 1}–${END_EPOCH}`;
  el('empty').hidden = out.length > 0;

  el('body').innerHTML = out.map((r, i) => `
    <tr>
      <td class="rank">${i + 1}</td>
      <td class="name">
        <a href="https://solana.org/sfdp-validators/${r.pk}" target="_blank" rel="noopener">${esc(r.name)}</a>
        <div class="pk">${r.pk.slice(0, 8)}…${r.pk.slice(-6)}</div>
      </td>
      <td class="rate ${rateClass(r.rate)}">${r.rate.toFixed(1)}%</td>
      <td class="num">${r.none} / ${r.evaluated}</td>
      <td class="num">${r.nb.toFixed(1)}%</td>
      <td class="num">${r.streak || '–'}</td>
      <td class="num">${fmt(Math.round(r.stake))}</td>
      <td class="num">${r.fdn ? fmt(Math.round(r.fdn)) : '–'}</td>
      <td><div class="spark">${[...r.s.slice(0, SPARK_MAX)].map((c, idx) =>
        `<i class="s-${c === '-' ? 'x' : c}" title="epoch ${END_EPOCH - idx}"></i>`).join('')}</div></td>
    </tr>`).join('');
}

function esc(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function renderSeg() {
  el('winseg').innerHTML = PRESETS.map(p =>
    `<button data-w="${p}" aria-pressed="${p === win}">${p}</button>`).join('');
  el('winseg').querySelectorAll('button').forEach(b => {
    b.onclick = () => { win = +b.dataset.w; el('custom').value = ''; renderSeg(); render(); };
  });
}

function downloadCsv() {
  const {out} = filtered();
  const head = ['rank','name','pubkey','participant_state','unmet_rate_pct','unmet','evaluated','missing',
    'not_bonus_rate_pct','consecutive_unmet','bonus','baseline','none','none_high_third_party_stake',
    'activated_stake_sol','sfdp_stake_sol','window_start_epoch','window_end_epoch'];
  const start = END_EPOCH - win + 1;
  const lines = [head.join(',')].concat(out.map((r, i) => [
    i + 1, `"${r.name.replace(/"/g, '""')}"`, r.pk, r.state, r.rate.toFixed(2), r.none, r.evaluated, r.missing,
    r.nb.toFixed(2), r.streak, r.bonus, r.baseline, r.none, r.party,
    Math.round(r.stake), Math.round(r.fdn), start, END_EPOCH,
  ].join(',')));
  const blob = new Blob(['\\ufeff' + lines.join('\\n')], {type:'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `sfdp_unmet_e${start}-${END_EPOCH}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

el('q').oninput = render;
el('minrate').oninput = render;
el('minev').onchange = render;
el('custom').oninput = e => {
  const v = parseInt(e.target.value, 10);
  if (v >= 1 && v <= HISTORY) { win = v; renderSeg(); render(); }
};
el('dl').onclick = downloadCsv;

renderSeg();
renderHead();
render();
</script>
</body>
</html>
"""


def collect(cluster: str, states: set[str], history: int, concurrency: int):
    participants = S.fetch_json(S.PARTICIPANTS_URL)
    if states:
        participants = [p for p in participants if p.get("state") in states]
    print(f"{len(participants)} validators", file=sys.stderr)

    end = S.latest_epoch(participants, cluster)
    window = list(range(end, end - history, -1))  # 新しい epoch が先頭
    key = S.stats_key(cluster)
    calc_key = "mnCalculatedStats" if cluster == "mainnet-beta" else "tnCalculatedStats"

    def one(p):
        try:
            d = S.fetch_validator(p["mainnetBetaPubkey"])
        except RuntimeError as exc:
            print(f"  skip {p['mainnetBetaPubkey']}: {exc}", file=sys.stderr)
            return None
        epochs = (d.get(key) or {}).get("epochs") or {}
        if not epochs:
            return None
        calc = d.get(calc_key) or {}
        pk = p["mainnetBetaPubkey"] if cluster == "mainnet-beta" else p.get("testnetPubkey")
        name = (d.get("mnName") if cluster == "mainnet-beta" else d.get("tnName") or d.get("mnName")) or ""
        return {
            "n": name,
            "p": pk or p["mainnetBetaPubkey"],
            "t": p.get("state", ""),
            "k": round(int(calc.get("activated_stake_last_epoch") or 0) / LAMPORTS),
            "f": round(int(calc.get("foundation_stake_last_epoch") or 0) / LAMPORTS),
            "s": "".join(CODE.get(epochs.get(str(e)), MISSING) for e in window),
        }

    rows = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for i, r in enumerate(pool.map(one, participants), 1):
            if r:
                rows.append(r)
            if i % 50 == 0:
                print(f"  {i}/{len(participants)}", file=sys.stderr)
    return rows, end


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", type=int, default=128, help="埋め込む epoch 数 (default: 128)")
    ap.add_argument("--cluster", choices=["mainnet-beta", "testnet"], default="mainnet-beta")
    ap.add_argument("--states", default="Approved")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--rps", type=float, default=4.0)
    ap.add_argument("--out", default="docs/index.html")
    ap.add_argument("--repo", default="https://github.com/nagumo-dawnlabs/sfdp-monitor")
    args = ap.parse_args()

    S.LIMITER = S.RateLimiter(args.rps)
    states = set() if args.states.lower() == "all" else {s.strip() for s in args.states.split(",") if s.strip()}

    rows, end = collect(args.cluster, states, args.history, args.concurrency)
    rows.sort(key=lambda r: (r["n"] or "\uffff").lower())

    html = HTML_TEMPLATE
    for token, value in [
        ("__HISTORY__", str(args.history)),
        ("__END__", str(end)),
        ("__START__", str(end - args.history + 1)),
        ("__SAMPLE__", rows[0]["p"] if rows else ""),
        ("__STATES__", args.states),
        ("__CLUSTER__", args.cluster),
        ("__GENERATED__", time.strftime("%Y-%m-%d %H:%M %Z")),
        ("__REPO__", args.repo),
        # データは最後に差し込む（バリデータ名がトークン文字列を含んでいても壊れないように）
        ("__DATA__", json.dumps(rows, ensure_ascii=False, separators=(",", ":"))),
    ]:
        html = html.replace(token, value)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, {len(rows)} validators, epoch {end - args.history + 1}-{end})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
