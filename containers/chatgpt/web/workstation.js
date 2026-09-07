// The pinned Selkies core owns the native desktop stream. ChatGPT files are untouched.
import '/src/selkies-core.js';
const byId = (id) => document.getElementById(id);
const send = (message) => window.postMessage(message, location.origin);
const notice = (text) => {
  byId('notice').textContent = text;
  byId('notice').hidden = !text;
};
function fit() {
  send({ type: 'setScaleLocally', value: true });
}
function resize() {
  const height = window.visualViewport?.height ?? window.innerHeight;
  document.documentElement.style.setProperty('--workstation-height', `${height}px`);
  requestAnimationFrame(fit);
}
window.visualViewport?.addEventListener('resize', resize);
window.addEventListener('resize', resize);
resize();
new ResizeObserver(fit).observe(byId('desktop'));
byId('fit').onclick = fit;
byId('keyboard').onclick = () => send({ type: 'showVirtualKeyboard' });
for (const id of ['clipboard', 'files', 'tools']) {
  byId(id).onclick = () => {
    const open = byId(`${id}-panel`).hidden;
    for (const name of ['clipboard', 'files', 'tools']) {
      byId(`${name}-panel`).hidden = !(name === id && open);
      byId(name).setAttribute('aria-expanded', String(name === id && open));
    }
    fit();
  };
}
byId('paste').onclick = () => {
  send({ type: 'clipboardUpdateFromUI', text: byId('clipboard-text').value });
  notice('Clipboard sent. Paste into the focused workstation input.');
};
byId('copy').onclick = async () => {
  try {
    await navigator.clipboard.writeText(byId('clipboard-text').value);
    notice('Copied to this device.');
  } catch {
    byId('clipboard-text').focus();
    byId('clipboard-text').select();
    notice('Clipboard permission was unavailable. Copy the selected text.');
  }
};
byId('upload').onclick = () => window.dispatchEvent(new CustomEvent('requestFileUpload'));
for (const [id, value] of Object.entries({
  terminal: 'xterm -fa Monospace -fs 12',
  browser: 'chromium --ozone-platform=x11',
  'show-app': 'wmctrl -xa chatgpt || launch-chatgpt',
})) byId(id).onclick = () => send({ type: 'command', value });
for (const [id, pipeline] of [['sound', 'audio'], ['microphone', 'microphone']]) {
  byId(id).onclick = () => send({
    type: 'pipelineControl', pipeline,
    enabled: byId(id).getAttribute('aria-pressed') !== 'true',
  });
}
byId('fullscreen').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch { notice('Fullscreen is unavailable in this browser.'); }
};
byId('reconnect').onclick = () => location.reload();
window.addEventListener('message', (event) => {
  if (event.origin !== location.origin || event.source !== window) return;
  const message = event.data;
  if (!message || typeof message !== 'object') return;
  if (message.type === 'pipelineStatusUpdate') {
    for (const [key, id] of [['audio', 'sound'], ['microphone', 'microphone']]) {
      if (typeof message[key] === 'boolean') byId(id).setAttribute('aria-pressed', String(message[key]));
    }
    if (typeof message.video === 'boolean') byId('connection').textContent = message.video ? 'Connected' : 'Reconnecting…';
  }
  if (message.type === 'clipboardContentUpdate' && document.activeElement !== byId('clipboard-text')) {
    byId('clipboard-text').value = message.content ?? message.text ?? '';
  }
  if (message.type === 'fileUpload') {
    const payload = message.payload ?? {};
    notice(`${payload.fileName ?? 'File transfer'}: ${payload.message ?? payload.status ?? ''}`);
  }
  if (message.type === 'serverSettings') fit();
});
window.addEventListener('offline', () => {
  byId('connection').textContent = 'Offline';
  notice('The workstation continues running. Reconnect when your connection returns.');
});
window.addEventListener('online', () => { notice('Connection restored. Reconnect if the display has not resumed.'); });
let installPrompt;
window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  installPrompt = event;
  byId('install').hidden = false;
});
byId('install').onclick = async () => {
  if (!installPrompt) return;
  await installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  byId('install').hidden = true;
};
window.addEventListener('appinstalled', () => { byId('install').hidden = true; });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
