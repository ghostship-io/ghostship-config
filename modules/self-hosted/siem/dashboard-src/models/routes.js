// ---- Routes: one row per selected route of a lane --------------------------
const ROUTE_FIELDS = {position: 'position', left: 'left', pace: 'pace', resetAt: 'resetAt'};
function readRoutes(rows) {
  const routes = new Map();
  for (const row of rows || []) {
    if (!row || !row.category || !row.provider || !row.model || !ROUTE_FIELDS[row.field]) { continue; }
    const key = [row.category, row.provider, row.model, row.effort || ''].join('|');
    let route = routes.get(key);
    if (!route) { route = {labels: row, n: {}}; routes.set(key, route); }
    route.n[row.field] = num(row.value);
  }
  return Array.from(routes.values());
}
// What a route is, in the order the picker ranks it, and why.
function routeView(route, now) {
  const l = route.labels;
  const n = route.n;
  const inferred = l.window === 'inferred';
  // An inferred window that has seen no limit is not 100%: it is unknown.
  const left = n.left === undefined || n.left === null || (inferred && n.left >= 1) ? null : n.left;
  const pace = PACE[l.pace_state] || null;
  const pa = n.pace === undefined || n.pace === null ? null : n.pace;
  const out = l.state === 'exhausted' || l.state === 'excluded' || l.state === 'unavailable';
  let kind = 'ok';
  let word = '';
  if (l.state === 'exhausted') { kind = 'out'; word = 'Out of quota'; }
  else if (l.state === 'excluded') { kind = 'out'; word = 'Excluded'; }
  else if (l.state === 'unavailable') { kind = 'out'; word = 'Unavailable'; }
  else if (l.state === 'reserved') { kind = 'held'; word = 'Held for review'; }
  else if (l.overspent === 'true' || l.pace_state === 'far_behind') { kind = 'bad'; word = 'Overspent'; }
  else if (l.pace_state === 'behind') { kind = 'warn'; word = 'Behind pace'; }
  else if (left === null && pa === null) { kind = 'unk'; }
  else if (pace) { kind = pace.tone; }
  const reset = n.resetAt === undefined ? null : n.resetAt;
  const provider = who(l.provider);
  const bar = paBar(out ? null : pa);
  return {
    key: [l.category, l.provider, l.model].join(':'),
    provider: l.provider, name: provider.name, icon: provider.icon, bg: provider.bg, fg: provider.fg,
    model: l.display_name || l.model, rawModel: l.model, effort: l.effort || '',
    position: n.position === undefined || n.position === null ? 1e9 : n.position,
    state: l.state, kind: kind, word: word, out: out,
    left: left, leftText: left === null ? '' : share(left),
    // spent routes say 0% left because the quota is gone, not because it is unknown
    // a daily or session window has no pace: only a long window is paced
    paceLong: pa !== null || out || /week|month|quota/i.test(l.window || ''),
    capacity: left === null ? (out ? '' : (inferred ? 'no limit seen' : 'capacity unknown' + filledBy(l.provider))) : share(left) + ' left',
    pa: pa, paText: out || pa === null ? '' : signed(pa), paKnown: bar.known && !out,
    paLeft: bar.left, paWidth: bar.width, paSide: bar.side,
    window: l.window || '', reset: reset,
    when: reset === null ? '' : (out ? back(reset, now) : (span(reset - now) === 'now' ? 'resets now' : 'resets in ' + span(reset - now))),
    estimated: inferred && left !== null,
    free: /^(free|promotion)$/.test(l.billing || ''),
    note: l.state === 'reserved' ? 'review headroom unknown' : '',
    untrusted: l.trust === 'untrusted',
    limited: l.sensitivity_sensitive === 'false',
  };
}
function laneRows(rows, now, free) {
  const views = readRoutes(rows).map((route) => routeView(route, now))
    .sort((a, b) => a.position - b.position || (a.name < b.name ? -1 : 1));
  const next = views.findIndex((view) => !view.out && view.kind !== 'held');
  return views.map((view, index) => ({...view, rank: index + 1, next: index === next}));
}

// ---- Account windows and calibration: readings joined to a provider's selected route ----
// An account whose lowest window reads zero is out of quota, whatever its route reading says.
function readAccounts(rows) {
  const accounts = new Map();
  for (const row of rows || []) {
    if (!row || !row.account || (row.field !== 'acctLeft' && row.field !== 'acctReset')) { continue; }
    const key = row.account + '|' + (row.quota_id || row.kind || '');
    let window = accounts.get(row.account);
    if (!window) { window = new Map(); accounts.set(row.account, window); }
    let entry = window.get(key);
    if (!entry) { entry = {left: null, reset: null, estimated: row.evidence === 'inferred'}; window.set(key, entry); }
    if (row.field === 'acctLeft') { entry.left = num(row.value); } else { entry.reset = num(row.value); }
  }
  const out = new Map();
  for (const [account, windows] of accounts) {
    const spent = Array.from(windows.values()).filter((w) => w.left !== null && w.left <= 0);
    if (spent.length) { out.set(account, {reset: Math.max(...spent.map((w) => w.reset || 0)) || null, estimated: spent.every((w) => w.estimated)}); }
  }
  return out;
}
const CALIBRATION = {
  ok: {tone: 'good', word: 'calibrated', hint: 'the limit reading has matched the provider so far'},
  warn: {tone: 'warn', word: 'calibration warning', hint: 'the provider refused while the reading showed headroom'},
  fail: {tone: 'bad', word: 'calibration failed', hint: 'the provider refused on consecutive days while the reading showed headroom'},
  unmeasured: {tone: 'unk', word: 'not calibrated yet', hint: 'no refusal or success has been counted for this route yet'},
};
function readCalibration(rows) {
  const states = new Map();
  for (const row of rows || []) {
    if (row && row.field === 'calibration' && row.provider && CALIBRATION[row.state]) { states.set(calibrationKey(row.provider, row.model), row.state); }
  }
  return states;
}
