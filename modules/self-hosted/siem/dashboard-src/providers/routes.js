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
    model: l.display_name || l.model, effort: l.effort || '',
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
  };
}
// The orchestrator is the picker's first orchestrator: the other candidates it lists are not orchestrators.
function configured(rows) {
  const list = (rows || []).filter((row) => row && row.category === 'orchestrator' && row.field === 'position');
  if (!list.length) { return rows; }
  const first = list.reduce((a, b) => (num(b.value) < num(a.value) ? b : a));
  return rows.filter((row) => !row || row.category !== 'orchestrator' || row.provider === first.provider);
}
// An account whose lowest window reads zero is out of quota, whatever its route reading says.
function readAccounts(rows) {
  const windows = new Map();
  for (const row of rows || []) {
    if (!row || !row.account || (row.field !== 'acctLeft' && row.field !== 'acctReset')) { continue; }
    const key = row.account + '|' + (row.quota_id || row.kind || '');
    let entry = windows.get(key);
    if (!entry) { entry = {account: row.account, left: null, reset: null, estimated: row.evidence === 'inferred'}; windows.set(key, entry); }
    if (row.field === 'acctLeft') { entry.left = num(row.value); } else { entry.reset = num(row.value); }
  }
  const out = new Map();
  for (const entry of windows.values()) {
    if (entry.left === null || entry.left > 0) { continue; }
    const known = out.get(entry.account);
    out.set(entry.account, {reset: Math.max(known ? known.reset || 0 : 0, entry.reset || 0) || null,
      estimated: (known ? known.estimated : true) && entry.estimated});
  }
  return out;
}
function laneRows(rows, now, accounts) {
  const views = readRoutes(rows).map((route) => routeView(route, now)).map((view) => {
    const account = accounts && accounts.get(view.provider);
    // The provider's account says it is spent: show that, with the window's reset, not the route's own reading.
    return account && !view.out ? {...view, kind: 'out', out: true, word: 'Out of quota', capacity: '0% left', leftText: '0%', left: 0,
      paKnown: false, paceLong: false, when: account.reset ? back(account.reset, now) : '',
      acctNote: 'account window spent' + (account.estimated ? ' · estimated' : '')} : view;
  }).sort((a, b) => a.position - b.position || (a.name < b.name ? -1 : 1))
    // One row per provider: a provider's other selected routes (the OpenCode Free routes filed under it) follow its first.
    .filter((view, index, list) => list.findIndex((other) => other.provider === view.provider) === index);
  const first = views.findIndex((view) => !view.out && view.kind !== 'held');
  // The rank is the picker's own position among all workers, so a paid worker reads 4th when free routes go first.
  return views.map((view, index) => ({...view, rank: view.position < 1e9 ? view.position : index + 1, first: index === first,
    next: index === first && view.position === 1,
    pace: !view.acctNote && (view.paKnown || (view.kind !== 'unk' && (view.paceLong || !!view.when)))}));
}
