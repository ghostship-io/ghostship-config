function freeView(account, now) {
  const base = providerView(account, now);
  const counts = account.free || {available: 0, unavailable: 0};
  const blocked = counts.available <= 0 && counts.unavailable > 0;
  const models = counts.available > 0 ? counts.available + ' model' + (counts.available === 1 ? '' : 's') : '';
  if (blocked) {
    return {...base, kind: 'out', head: 'Blocked', bar: null, chips: [], sort: 0, models: '',
      sub: freeWhy(account.reasons).slice(0, 3).join(', ') || counts.unavailable + ' models unavailable'};
  }
  if (base.bar && base.kind !== 'unk') {
    return {...base, sort: base.kind === 'out' ? 0 : 1, models: [models, base.detail].filter(Boolean).join(' · '), sub: ''};
  }
  return {...base, kind: 'unk', head: 'No limit seen', bar: null, chips: [], sort: 2, models: models, sub: ''};
}
function sortViews(views) {
  const share = (view) => (view.left === null ? 2 : view.left);
  return views.sort((a, b) => a.sort - b.sort || share(a) - share(b) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}
const NOW = (value) => (num(value) || 0) / 1000;
const isFreeRoute = (row) => /^(free|promotion)$/.test(row.billing || '');
context.handlebars.registerHelper('laneRows', function(rows, now, lane, limit) {
  const free = lane === 'free';
  const all = laneRows(configured(rows).filter((row) => row && row.category === (lane === 'orchestrator' ? 'orchestrator' : 'worker')
    && (lane === 'orchestrator' || free === isFreeRoute(row))), NOW(now), free ? readAccounts(rows) : null);
  const shown = limit ? all.slice(0, limit) : all;
  return {rows: shown, more: all.length - shown.length, count: all.length};
});
context.handlebars.registerHelper('providerRows', function(rows, now) {
  return sortViews(readWindows(rows).filter((account) => account.account !== 'openrouter').map((account) => providerView(account, NOW(now))).filter((view) => !view.free));
});
context.handlebars.registerHelper('freeRows', function(rows, now) {
  return sortViews(readWindows(rows).filter((account) => account.free || account.avail || account.windows.size).map((account) => freeView(account, NOW(now))));
});
context.handlebars.registerHelper('headline', function(rows, now) {
  rows = configured(rows);
  const at = NOW(now);
  const routes = readRoutes((rows || []).filter((row) => row && row.category)).map((route) => routeView(route, at));
  const pick = (list) => list.sort((a, b) => a.position - b.position).find((view) => !view.out && view.kind !== 'held') || null;
  const orchestrator = pick(routes.filter((r) => r.key.startsWith('orchestrator:')));
  const worker = pick(routes.filter((r) => r.key.startsWith('worker:')));
  const providers = readWindows(rows).filter((account) => account.windows.size || account.missing || account.avail)
    .map((account) => providerView(account, at));
  const free = readWindows(rows).filter((account) => account.free);
  const pickText = (view) => view ? {name: view.name, icon: view.icon, bg: view.bg, fg: view.fg, model: view.model,
    detail: [view.word, view.capacity, view.when].filter(Boolean).join(' · '), kind: view.kind} : null;
  const names = (list) => list.map((view) => view.name);
  const out = providers.filter((view) => view.kind === 'out');
  const over = providers.filter((view) => view.kind === 'bad');
  const behind = providers.filter((view) => view.kind === 'warn');
  const unknown = providers.filter((view) => view.kind === 'unk');
  const blocked = free.map((account) => freeView(account, at)).filter((view) => view.kind === 'out');
  return {orchestrator: pickText(orchestrator), worker: pickText(worker),
    out: {count: out.length + blocked.length, text: names(out.concat(blocked)).join(', ')},
    over: {count: over.length, text: names(over).join(', ')},
    behind: {count: behind.length, text: names(behind).join(', ')},
    unknown: {count: unknown.length, text: names(unknown).join(', ')}};
});
