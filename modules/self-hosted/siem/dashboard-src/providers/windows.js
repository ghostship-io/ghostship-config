// ---- Providers: the account windows -----------------------------------------
function readWindows(rows) {
  const accounts = new Map();
  const entry = (account) => {
    let value = accounts.get(account);
    if (!value) { value = {account: account, windows: new Map(), avail: null, missing: false, learning: false, free: null, reasons: [], announced: null}; accounts.set(account, value); }
    return value;
  };
  for (const row of rows || []) {
    if (!row || !row.account || row.category || row.field === 'acctLeft' || row.field === 'acctReset') { continue; }
    const value = num(row.value);
    const account = entry(row.account);
    if (row.field === 'reported_missing') { if (value === 1) { account.missing = true; } continue; }
    if (row.field === 'availability') { if (value === 1) { account.avail = {state: row.state, basis: row.basis, reason: row.reason}; } continue; }
    if (row.field === 'learning') { if (value === 1) { account.learning = true; } continue; }
    if (row.field === 'free_models') {
      account.free = account.free || {available: 0, unavailable: 0};
      if (row.state === 'available') { account.free.available = value || 0; }
      if (row.state === 'unavailable') { account.free.unavailable = value || 0; }
      continue;
    }
    if (row.field === 'free_reason') { if (value > 0) { account.reasons.push({reason: String(row.reason || ''), count: value, obsolete: row.obsolete === 'true'}); } continue; }
    if (row.field === 'announced') {
      const at = Date.parse(row.reset_at || '') / 1000;
      if (row.confidence === 'confirmed' && Number.isFinite(at) && (!account.announced || at < account.announced)) { account.announced = at; }
      continue;
    }
    if (!row.quota_id && !row.kind) { continue; }
    const key = (row.kind || '') + '|' + (row.quota_id || '');
    let window = account.windows.get(key);
    if (!window) {
      window = {label: String(row.label || '').replace(/^Quota\s*·\s*/, ''), kind: row.kind || '', inferred: row.evidence === 'inferred',
        left: null, expected: null, resetAt: null, order: 99, rolling: false, state: '', pace: null, notUsed: false};
      account.windows.set(key, window);
    }
    if (row.not_used === 'true') { window.notUsed = true; }
    if (row.field === 'left') { window.left = value; }
    else if (row.field === 'expected') { window.expected = value; }
    else if (row.field === 'resetAt') { window.resetAt = value; }
    else if (row.field === 'order') { window.order = value === null ? 99 : value; }
    else if (row.field === 'rolling') { window.rolling = value === 1; }
    else if (row.field === 'pace_state' && value === 1) { window.state = row.state; }
    else if (row.field === 'pace_delta') { window.pace = value; }
  }
  return Array.from(accounts.values());
}
// A window's reading is known unless it is an inferred window that has seen no limit.
function windowKnown(window) {
  return window.left !== null && !(window.inferred && window.left >= 1);
}
function freeWhy(reasons) {
  const groups = new Map();
  for (const entry of reasons || []) {
    const until = entry.reason.match(/until (\d{4}-\d\d-\d\dT[\d:]+Z)/);
    let label;
    if (until) { label = 'cooling until ' + clock(Date.parse(until[1]) / 1000); }
    else if (/not offered/i.test(entry.reason)) { label = 'not offered'; }
    else if (entry.obsolete || /obsolete|deprecated|superseded/i.test(entry.reason)) { label = 'obsolete'; }
    else if (/exclud/i.test(entry.reason)) { label = 'excluded'; }
    else { label = entry.reason.replace(/_/g, ' ').slice(0, 28) || 'unavailable'; }
    groups.set(label, (groups.get(label) || 0) + entry.count);
  }
  return Array.from(groups.entries()).sort((a, b) => b[1] - a[1]).map(([label, count]) => count + ' ' + label);
}
// One provider: its lowest known window leads; unknown windows stay unknown.
function providerView(account, now) {
  const who_ = who(account.account);
  const windows = Array.from(account.windows.values()).sort((a, b) => a.order - b.order);
  const used = windows.filter((w) => !w.notUsed);
  const known = used.filter(windowKnown);
  const unknown = used.filter((w) => !windowKnown(w));
  const view = {account: account.account, name: who_.name, icon: who_.icon, bg: who_.bg, fg: who_.fg,
    kind: 'unk', head: 'Unknown', detail: '', bar: null, chips: [], partial: false, free: account.free,
    sort: 2, announced: account.announced && account.announced > now - 86400 && account.announced < now + 7 * 86400 ? account.announced : null, left: null, pa: null};
  const pool = account.free;
  if (known.length) {
    const lead = known.reduce((a, b) => (b.left < a.left ? b : a));
    const pace = PACE[lead.state] || null;
    const out = lead.left <= 0;
    const longWindow = lead.expected !== null && !lead.rolling && !/session|hour|daily|minute|inferred/i.test(lead.kind);
    view.left = lead.left;
    view.pa = lead.pace;
    view.kind = out ? 'out' : (pace && longWindow ? pace.tone : 'ok');
    view.head = out ? 'Out of quota' : share(lead.left) + ' left';
    view.bar = {width: Math.round(lead.left * 1000) / 10, tick: longWindow ? Math.round(lead.expected * 1000) / 10 : null,
      estimated: lead.inferred};
    const bits = [lead.label];
    if (lead.pace !== null && longWindow && !out) { bits.push((lead.pace < 0 ? '▼ ' : lead.pace > 0 ? '▲ ' : '● ') + signed(lead.pace) + ' Paced Availability'); }
    if (lead.resetAt !== null && !lead.rolling) { bits.push(back(lead.resetAt, now)); }
    if (view.announced) { bits.push('⚡ reset confirmed' + (view.announced > now ? ' in ' + span(view.announced - now) : ' · done')); }
    if (out && lead.pace === null && account.account === 'antigravity') { bits.push('no Paced Availability yet · #468'); }
    view.detail = bits.join(' · ');
    view.chips = used.filter((w) => w !== lead).map((w) => ({label: w.label,
      text: windowKnown(w) ? (w.left <= 0 ? 'out' : share(w.left)) : 'unknown', kind: windowKnown(w) ? (w.left <= 0 ? 'out' : 'ok') : 'unk'}));
    view.partial = unknown.length > 0;
    view.sort = out ? 0 : 1;
  } else if (account.missing) {
    view.head = 'Unknown'; view.detail = 'limits could not be read · collector source failed' + filledBy(account.account);
  } else if (account.avail && account.avail.state === 'unavailable') {
    view.kind = 'out'; view.head = 'Unavailable'; view.detail = account.avail.reason || ''; view.sort = 0;
  } else if (used.length && unknown.length) {
    view.detail = 'no limit seen yet · ' + unknown.length + ' estimated window' + (unknown.length === 1 ? '' : 's');
  } else if (windows.length && !used.length) {
    view.kind = 'idle'; view.head = 'Not used'; view.detail = 'every window is marked not used'; view.sort = 3;
  } else {
    view.detail = (account.learning ? 'no limit published · learning' : 'no limit published · no usage reading') + filledBy(account.account);
  }
  view.notUsed = windows.length - used.length;
  return view;
}
