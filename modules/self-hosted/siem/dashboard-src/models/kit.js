// Presentation only. Every number is a collector gauge; this code orders,
// words and colours them and never turns a missing reading into a number.
const PROVIDERS = {
  claude: {name: 'Claude', icon: '✳', bg: '#d97757', fg: '#fff'},
  codex: {name: 'Codex', icon: '⊛', bg: '#e8e8e8', fg: '#111'},
  ollama: {name: 'Ollama', icon: '◉', bg: '#f2f2f2', fg: '#111'},
  'opencode-go': {name: 'OpenCode Go', icon: '{}', bg: '#2b2f3a', fg: '#7dd3fc'},
  antigravity: {name: 'Antigravity', icon: 'A', bg: 'linear-gradient(135deg,#4f8cff,#c86bfa)', fg: '#fff'},
  grok: {name: 'Grok', icon: '⊘', bg: '#000', fg: '#fff'},
  commandCode: {name: 'Command Code', icon: 'C', bg: '#2b2f3a', fg: '#e6e8ee'},
  opencode: {name: 'OpenCode Zen', icon: 'O', bg: '#2b2f3a', fg: '#e6e8ee'},
  'cloudflare-workers-ai': {name: 'Cloudflare'},
  'kilo-keyed': {name: 'Kilo (keyed)', icon: 'K'},
  openrouter: {name: 'OpenRouter'},
  nvidia: {name: 'NVIDIA'},
  ovh: {name: 'OVH'},
  zai: {name: 'Zai'},
  deepseek: {name: 'DeepSeek'},
  orcarouter: {name: 'Orcarouter'},
};
function who(id) {
  const known = PROVIDERS[id] || {};
  const text = String(id || '');
  return {
    name: known.name || text.split(/[-_\s]+/).filter(Boolean).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
    icon: known.icon || text.charAt(0).toUpperCase(),
    bg: known.bg || '#2b2f3a',
    fg: known.fg || '#e6e8ee',
  };
}
function num(value) {
  if (value === null || value === undefined || value === '') { return null; }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
function round1(value) { return Math.round(value * 10) / 10; }
// The span until a reset: minutes, hours, then days.
function span(seconds) {
  if (seconds <= 0) { return 'now'; }
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) { return minutes + 'm'; }
  if (minutes < 2880) { return Math.floor(minutes / 60) + 'h ' + (minutes % 60) + 'm'; }
  return round1(minutes / 1440) + 'd';
}
function back(reset, now) {
  if (reset === null || reset === undefined) { return ''; }
  const left = span(reset - now);
  return left === 'now' ? 'back now' : 'back in ' + left;
}
// The share that is left: a half point is kept, a whole reading has no zero.
function share(left) {
  const tenths = Math.round(left * 1000);
  return (tenths % 10 === 0 ? String(tenths / 10) : (tenths / 10).toFixed(1)) + '%';
}
function signed(points) {
  const value = round1(Math.abs(points));
  return (points > 0 ? '+' : points < 0 ? '−' : '') + value;
}
function clock(seconds) {
  const moment = new Date(seconds * 1000);
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const pad = (n) => String(n).padStart(2, '0');
  return moment.getUTCDate() + ' ' + months[moment.getUTCMonth()] + ' ' + pad(moment.getUTCHours()) + ':' + pad(moment.getUTCMinutes()) + 'Z';
}
// A pace band to a tone and a word. spent is out of quota, never "on pace".
const PACE = {
  ahead: {tone: 'good', word: 'ahead of pace'},
  on_pace: {tone: 'ok', word: 'on pace'},
  behind: {tone: 'warn', word: 'behind pace'},
  far_behind: {tone: 'bad', word: 'overspent'},
  spent: {tone: 'out', word: 'out of quota'},
};
// The bar of Paced Availability: centre line is on pace, right is ahead and
// left is overspent. A missing reading gets no bar and no number.
function paBar(points) {
  if (points === null) { return {known: false, left: 50, width: 0, side: 'unk'}; }
  const half = Math.min(100, Math.abs(points)) / 2;
  return {known: true, left: points < 0 ? 50 - half : 50, width: Math.max(half, 1.5), side: points < 0 ? 'neg' : 'pos'};
}

// Who fills a reading the collector does not publish yet: the sub-issue of the epic.
const FILLED_BY = {claude: '#465', commandCode: '#466'};
function filledBy(provider) { return FILLED_BY[provider] ? ' · ' + FILLED_BY[provider] : ''; }

function ordinal(n) {
  const rest = n % 100;
  const suffix = rest >= 11 && rest <= 13 ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[n % 10] || 'th');
  return n + suffix;
}
// The model id the calibration series names: a path separator and an at sign become an underscore.
function calibrationKey(provider, model) { return provider + '|' + String(model || '').replace(/[@/]/g, '_'); }
