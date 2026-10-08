const REPORT = "http://127.0.0.1:9977";
const WORKER = Math.random().toString(36).slice(2);

async function post(path, payload) {
  try {
    await fetch(REPORT + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {}
}

function waitComplete(tabId, timeoutMs) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(false);
    }, timeoutMs || 30000);
    const listener = (id, info) => {
      if (id === tabId && info.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(true);
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

const EVALUATORS = {
  text: () => (document.body ? document.body.innerText : ""),
  title: () => document.title,
  product_links: () => document.querySelectorAll('a[href*="/p/"]').length,
  prices: () => (document.body.innerText.match(/\$\s?\d/g) || []).length,
  cookie_len: () => document.cookie.length,
  first_product: () => {
    const link = document.querySelector('a[href*="/p/"]');
    return link ? link.href : null;
  },
};

async function execute(cmd) {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab) return { error: "no active tab" };
  if (cmd.op === "navigate") {
    await chrome.tabs.update(tab.id, { url: cmd.url });
    await waitComplete(tab.id, 45000);
    const info = await chrome.tabs.get(tab.id);
    return { url: info.url, title: info.title };
  }
  if (cmd.op === "reload") {
    await chrome.tabs.reload(tab.id);
    await waitComplete(tab.id, 45000);
    const info = await chrome.tabs.get(tab.id);
    return { url: info.url, title: info.title };
  }
  if (cmd.op === "evaluate") {
    const func = EVALUATORS[cmd.name];
    if (!func) return { error: "unknown evaluator" };
    const results = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func });
    return { value: results[0].result };
  }
  if (cmd.op === "click_selector") {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      args: [cmd.selector],
      func: (selector) => {
        const element = document.querySelector(selector);
        if (!element) return false;
        element.click();
        return true;
      },
    });
    return { clicked: results[0].result };
  }
  return { error: "unknown op" };
}

setInterval(async () => {
  try {
    const response = await fetch(REPORT + "/ext/next?worker=" + WORKER, { cache: "no-store" });
    if (response.status !== 200) return;
    const command = await response.json();
    let result;
    try {
      result = await execute(command);
    } catch (error) {
      result = { error: String(error) };
    }
    await post("/ext/result", { id: command.id, worker: WORKER, result });
  } catch (error) {}
}, 700);

post("/ext/hello", { worker: WORKER, ua: navigator.userAgent });
