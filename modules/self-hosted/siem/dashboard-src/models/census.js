// ---- Census: every candidate route, counted by the one reason it is or is not picked ----
const REASONS = [
  {key: 'pickable', label: 'Pickable', tone: 'good', hint: 'available and not overspent'},
  {key: 'overspent', label: 'Overspent', tone: 'bad', hint: 'spending far faster than its allowance pace'},
  {key: 'exhausted', label: 'Out of quota', tone: 'out', hint: 'its allowance is spent until the reset'},
  {key: 'untrusted', label: 'Untrusted', tone: 'trust', hint: 'a verified outcome contradicted the route'},
  {key: 'held', label: 'Held for review', tone: 'held', hint: 'headroom is reserved for review work'},
  {key: 'cooling', label: 'Cooling down', tone: 'warn', hint: 'rate limited until a recorded time'},
  {key: 'unavailable', label: 'Not offered', tone: 'idle', hint: 'the T3 instance does not offer the route'},
  {key: 'obsolete', label: 'Obsolete', tone: 'idle', hint: 'deprecated or superseded within its family (label from #469)'},
  {key: 'excluded', label: 'Excluded by policy', tone: 'idle', hint: 'the owner policy excludes the route'},
  {key: 'public', label: 'Public pool', tone: 'idle', hint: 'free but not on the owner-approved list, so never picked'},
];
// The first reason that applies: a route is counted once.
function routeReason(l) {
  const reason = String(l.reason || '');
  if (l.trust === 'excluded' || l.state === 'excluded') { return 'excluded'; }
  // The collector's obsolete label wins; the reason text is the fallback until every route carries it.
  if (l.obsolete === 'true' || /obsolete|deprecated|superseded/i.test(reason)) { return 'obsolete'; }
  if (/^(free|promotion)$/.test(l.billing || '') && l.approved_free === 'false') { return 'public'; }
  if (l.state === 'unavailable') { return /cooling/i.test(reason) ? 'cooling' : 'unavailable'; }
  if (l.state === 'exhausted') { return 'exhausted'; }
  if (l.trust === 'untrusted') { return 'untrusted'; }
  if (l.state === 'reserved') { return 'held'; }
  if (l.overspent === 'true' || l.pace_state === 'far_behind') { return 'overspent'; }
  return 'pickable';
}
function readCensus(rows, category) {
  const providers = new Map();
  for (const row of rows || []) {
    if (!row || row.field !== 'census' || !row.provider || (category && row.category !== category)) { continue; }
    const count = num(row.value);
    if (count === null || count <= 0) { continue; }
    let entry = providers.get(row.provider);
    if (!entry) { entry = {provider: row.provider, total: 0, limited: 0, by: {}}; providers.set(row.provider, entry); }
    const key = routeReason(row);
    entry.by[key] = (entry.by[key] || 0) + count;
    entry.total += count;
    if (row.sensitivity_sensitive === 'false') { entry.limited += count; }
  }
  return providers;
}
function censusView(entry) {
  if (!entry) { return null; }
  const parts = REASONS.filter((reason) => entry.by[reason.key]).map((reason) => ({
    key: reason.key, label: reason.label, tone: reason.tone, count: entry.by[reason.key],
    pct: Math.round(entry.by[reason.key] * 1000 / entry.total) / 10}));
  const skipped = parts.filter((part) => part.key !== 'pickable');
  return {total: entry.total, pickable: entry.by.pickable || 0, parts: parts, limited: entry.limited,
    partial: entry.limited > 0 && entry.limited < entry.total,
    text: (entry.by.pickable || 0) + ' of ' + entry.total + ' pickable',
    skipped: skipped.map((part) => part.count + ' ' + part.label.toLowerCase()).join(' · ')};
}
