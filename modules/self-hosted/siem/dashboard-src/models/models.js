// ---- Lanes: one row per provider, its selected route and why its other routes are skipped ----
const NOW = (value) => (num(value) || 0) / 1000;
function providerRoute(view, census, account, calibration, now) {
  if (view) {
    const routed = {...view, census: censusView(census)};
    if (calibration) { routed.calib = calibration; }
    if (account && !view.out) {
      // The provider's account says it is spent: show that, with the window's reset, not the route's own reading.
      return {...routed, kind: 'out', out: true, word: 'Out of quota', capacity: '0% left', leftText: '0%', left: 0,
        paKnown: false, paceLong: false, when: account.reset ? back(account.reset, now) : '',
        acctNote: 'account window spent' + (account.estimated ? ' · estimated' : '')};
    }
    return routed;
  }
  const stub = censusView(census);
  const top = stub && stub.parts.filter((part) => part.key !== 'pickable').sort((a, b) => b.count - a.count)[0];
  const identity = who(census.provider);
  // Routes that can be picked but none is selected: unknown, not out. Only a provider with nothing pickable is out.
  const open = !!(stub && stub.pickable > 0);
  // A spent account blocks every route of the provider, selected or not.
  if (account) {
    return {provider: census.provider, name: identity.name, icon: identity.icon, bg: identity.bg, fg: identity.fg,
      model: '', noRoute: true, paceLong: false, kind: 'out', out: true, word: 'Out of quota', capacity: '', leftText: '',
      paKnown: false, paText: '', paLeft: 50, paWidth: 0, paSide: 'unk', when: account.reset ? back(account.reset, now) : '',
      acctNote: 'account window spent' + (account.estimated ? ' · estimated' : ''), position: 1e9, next: false, census: stub};
  }
  return {provider: census.provider, name: identity.name, icon: identity.icon, bg: identity.bg, fg: identity.fg,
    model: '', noRoute: true, paceLong: false, kind: open ? 'unk' : 'out', out: !open,
    word: open ? '' : (top ? 'All ' + top.label.toLowerCase() : 'No route'),
    capacity: open ? 'no route selected' : '', leftText: '', paKnown: false, paText: '', paLeft: 50, paWidth: 0, paSide: 'unk', when: '',
    position: 1e9, next: false, census: stub};
}
// The orchestrator is the picker's first orchestrator: the other candidates it lists are not orchestrators.
function configured(rows) {
  const list = (rows || []).filter((row) => row && row.category === 'orchestrator' && row.field === 'position');
  if (!list.length) { return rows; }
  const first = list.reduce((a, b) => (num(b.value) < num(a.value) ? b : a));
  return rows.filter((row) => !row || row.category !== 'orchestrator' || row.provider === first.provider);
}
function laneProviders(rows, now, lane) {
  const category = lane === 'orchestrator' ? 'orchestrator' : 'worker';
  const selected = new Map();
  // One route per provider: the picker's own order decides when two routes of a provider are selected.
  for (const route of readRoutes((rows || []).filter((row) => row && row.category === category))) {
    const view = routeView(route, now);
    const known = selected.get(route.labels.provider);
    if (!known || view.position < known.position) { selected.set(route.labels.provider, view); }
  }
  const census = readCensus(rows, category);
  const accounts = lane === 'free' ? readAccounts(rows) : new Map();
  const calibration = lane === 'free' ? readCalibration(rows) : new Map();
  // A provider whose every route is in the public pool has no approved worker: it is counted, never listed.
  const listed = Array.from(census.keys()).filter((provider) => {
    const entry = census.get(provider);
    return lane !== 'free' || selected.has(provider) || entry.by.public !== entry.total;
  });
  const providers = new Set([...selected.keys(), ...listed]);
  const list = Array.from(providers).map((provider) => {
    const view = selected.get(provider);
    const state = view ? calibration.get(calibrationKey(provider, view.rawModel)) : null;
    return providerRoute(view, census.get(provider), accounts.get(provider),
      state ? {...CALIBRATION[state], state: state} : null, now);
  });
  list.sort((a, b) => a.position - b.position || (b.census ? b.census.total : 0) - (a.census ? a.census.total : 0)
    || (a.name < b.name ? -1 : 1));
  const first = list.findIndex((view) => !view.noRoute && !view.out && view.kind !== 'held');
  // The rank is the picker's own position among all workers, so a paid worker reads 4th when free routes go first.
  return list.map((view, index) => ({...view, rank: view.position < 1e9 ? view.position : '·', first: index === first,
    next: index === first && view.position === 1, many: !!(view.census && view.census.total > 1),
    pace: !view.noRoute && !view.acctNote && (view.paKnown || (view.kind !== 'unk' && (view.paceLong || !!view.when)))}));
}
context.handlebars.registerHelper('modelRows', function(rows, now, lane, limit) {
  const all = laneProviders(configured(rows), NOW(now), lane);
  const shown = limit ? all.slice(0, limit) : all;
  return {rows: shown, more: all.length - shown.length, count: all.length};
});
// ---- Summary tiles ----
function nextRoute(rows, now, lane) {
  const view = laneProviders(rows, now, lane).find((entry) => entry.first);
  if (!view) { return null; }
  // A paid worker is tried after the free routes: say where the picker puts it.
  const order = lane === 'paid' && view.position > 1 && view.position < 1e9 ? 'tried ' + ordinal(view.position) + ', after the free routes' : '';
  return {name: view.name, icon: view.icon, bg: view.bg, fg: view.fg, model: view.model, kind: view.kind,
    detail: [view.word, view.capacity, view.when, order].filter(Boolean).join(' · ')};
}
context.handlebars.registerHelper('modelSummary', function(rows, now, scope) {
  rows = configured(rows);
  const at = NOW(now);
  const census = new Map();
  let total = 0;
  let pickable = 0;
  let limited = 0;
  const by = {};
  for (const category of ['orchestrator', 'worker']) {
    for (const entry of readCensus(rows, category).values()) {
      total += entry.total; pickable += entry.by.pickable || 0; limited += entry.limited;
      for (const key of Object.keys(entry.by)) { by[key] = (by[key] || 0) + entry.by[key]; }
    }
  }
  const top = REASONS.filter((reason) => reason.key !== 'pickable' && by[reason.key])
    .sort((a, b) => by[b.key] - by[a.key]).slice(0, 2).map((reason) => by[reason.key] + ' ' + reason.label.toLowerCase());
  return {orchestrator: scope === 'paid' ? nextRoute(rows, at, 'orchestrator') : null,
    worker: nextRoute(rows, at, scope === 'paid' ? 'paid' : 'free'),
    pickable: {count: pickable, of: total}, skipped: {count: total - pickable, text: top.join(' · ')},
    limited: {count: limited}};
});
// ---- Why routes are picked or skipped, across the lanes of the page ----
context.handlebars.registerHelper('modelReasons', function(rows) {
  rows = configured(rows);
  const by = {};
  const providers = {};
  let total = 0;
  let limited = 0;
  for (const category of ['orchestrator', 'worker']) {
    for (const entry of readCensus(rows, category).values()) {
      total += entry.total; limited += entry.limited;
      for (const key of Object.keys(entry.by)) {
        by[key] = (by[key] || 0) + entry.by[key];
        providers[key] = providers[key] || new Map();
        providers[key].set(entry.provider, (providers[key].get(entry.provider) || 0) + entry.by[key]);
      }
    }
  }
  const peak = Math.max(1, ...Object.values(by));
  const list = REASONS.filter((reason) => by[reason.key]).map((reason) => ({
    key: reason.key, label: reason.label, tone: reason.tone, hint: reason.hint, count: by[reason.key],
    width: Math.max(2, Math.round(by[reason.key] * 1000 / peak) / 10),
    who: Array.from(providers[reason.key].entries()).sort((a, b) => b[1] - a[1]).slice(0, 4)
      .map(([provider, count]) => who(provider).name + ' ' + count).join(' · ')}));
  return {list: list, total: total, limited: limited, empty: total === 0};
});
