(() => {
  "use strict";

  const transport = window.__codexWebTransport;
  if (!transport) return;

  const nativeCreateElement = Document.prototype.createElement;
  const elementSurfaces = new WeakMap();
  const mountingSurfaces = new Map();
  const surfaces = new Map();
  const officialSnapshots = new Map();
  const pendingSidebarCommands = new Map();
  const conversationAttribute = "data-browser-sidebar-conversation-id";
  const tabAttribute = "data-browser-sidebar-browser-tab-id";
  let keyboardSurface;
  let latestSidebarSync;

  function surfaceKey(conversationId, browserTabId) {
    return conversationId && browserTabId
      ? `${conversationId}\0${browserTabId}`
      : null;
  }

  function normalizeUrl(value) {
    try {
      return new URL(value).href;
    } catch {
      return value || "";
    }
  }

  function browserDisplayUrl(value) {
    try {
      const url = new URL(value);
      if (url.protocol === "about:") return value;
      return `${url.host}${url.pathname === "/" ? "" : url.pathname}${url.search}${url.hash}`;
    } catch {
      return value || "";
    }
  }

  function dispatch(element, name, details = {}) {
    const event = new Event(name);
    for (const [key, value] of Object.entries(details)) {
      Object.defineProperty(event, key, { enumerable: true, value });
    }
    element.dispatchEvent(event);
  }

  function sendCommand(surface, command, details = {}) {
    if (!surface.conversationId || !surface.browserTabId) return;
    transport.send({
      type: "browser-surface-command",
      command,
      conversationId: surface.conversationId,
      browserTabId: surface.browserTabId,
      ...details,
    });
  }

  function findSurface(conversationId, browserTabId) {
    if (browserTabId) {
      return surfaces.get(surfaceKey(conversationId, browserTabId)) || null;
    }
    for (const surface of surfaces.values()) {
      if (surface.conversationId === conversationId) return surface;
    }
    return null;
  }

  function reconcileNavigation(surface) {
    const snapshot = officialSnapshots.get(surface.key);
    const target =
      surface.desiredUrl ||
      surface.initialUrl ||
      (surface.state.url ? null : snapshot?.url);
    if (
      target &&
      normalizeUrl(target) !== normalizeUrl(surface.state.url) &&
      Date.now() - surface.lastNavigationSentAt > 500
    ) {
      surface.pendingNavigation = target;
      surface.lastNavigationSentAt = Date.now();
      sendCommand(surface, "navigate", { url: target });
      clearTimeout(surface.navigationTimer);
      surface.navigationTimer = setTimeout(
        () => reconcileNavigation(surface),
        600,
      );
    }
  }

  function subscribe(surface) {
    const conversationId = surface.element.getAttribute(conversationAttribute);
    const browserTabId = surface.element.getAttribute(tabAttribute);
    const nextKey = surfaceKey(conversationId, browserTabId);
    if (nextKey === surface.key) return;
    if (surface.key) {
      surfaces.delete(surface.key);
      transport.send({
        type: "browser-surface-unsubscribe",
        conversationId: surface.conversationId,
        browserTabId: surface.browserTabId,
      });
    }
    surface.conversationId = conversationId;
    surface.browserTabId = browserTabId;
    surface.key = nextKey;
    if (!nextKey) return;
    const previous = surfaces.get(nextKey) || mountingSurfaces.get(nextKey);
    if (previous && previous !== surface) {
      clearTimeout(previous.navigationTimer);
      previous.element.remove();
    }
    mountingSurfaces.delete(nextKey);
    surface.desiredUrl =
      officialSnapshots.get(nextKey)?.url || surface.initialUrl || null;
    surfaces.set(nextKey, surface);
    transport.send({
      type: "browser-surface-subscribe",
      conversationId,
      browserTabId,
    });
    reconcileNavigation(surface);
    setTimeout(() => dispatch(surface.element, "did-attach"), 0);
  }

  function pointerPosition(element, event) {
    const bounds = element.getBoundingClientRect();
    return {
      xRatio: bounds.width > 0 ? (event.clientX - bounds.left) / bounds.width : 0,
      yRatio: bounds.height > 0 ? (event.clientY - bounds.top) / bounds.height : 0,
    };
  }

  function buttonName(button) {
    return button === 1 ? "middle" : button === 2 ? "right" : "left";
  }

  function surfaceAtPoint(x, y) {
    for (const surface of [...surfaces.values()].reverse()) {
      if (getComputedStyle(surface.element).display === "none") continue;
      const bounds = surface.element.getBoundingClientRect();
      if (
        x >= bounds.left &&
        x <= bounds.right &&
        y >= bounds.top &&
        y <= bounds.bottom
      ) {
        return surface;
      }
    }
    return null;
  }

  function createWebview(documentObject) {
    const element = nativeCreateElement.call(documentObject, "div");
    const image = nativeCreateElement.call(documentObject, "img");
    const surface = {
      browserTabId: null,
      conversationId: null,
      desiredUrl: null,
      element,
      generation: 0,
      image,
      initialUrl: null,
      key: null,
      lastNavigationSentAt: 0,
      navigationTimer: null,
      pendingNavigation: null,
      state: {},
    };
    elementSurfaces.set(element, surface);

    element.dataset.codexWebviewBridge = "";
    element.tabIndex = 0;
    element.style.cssText =
      "display:block;position:absolute;inset:0;width:100%;height:100%;overflow:hidden;background:#fff;outline:none";
    image.alt = "";
    image.draggable = false;
    image.style.cssText =
      "display:block;width:100%;height:100%;object-fit:fill;user-select:none;-webkit-user-drag:none";
    element.append(image);

    const nativeSetAttribute = element.setAttribute.bind(element);
    element.setAttribute = (name, value) => {
      nativeSetAttribute(name, value);
      if (name === conversationAttribute || name === tabAttribute) {
        queueMicrotask(() => subscribe(surface));
      } else if (
        name === "src" &&
        value &&
        value !== "about:blank" &&
        !surface.state.url
      ) {
        surface.initialUrl = String(value);
        surface.desiredUrl = surface.initialUrl;
        queueMicrotask(() => reconcileNavigation(surface));
      }
    };
    element.loadURL = (url) => sendCommand(surface, "navigate", { url });
    element.getURL = () => surface.state.url || "";
    element.getTitle = () => surface.state.title || "";
    element.canGoBack = () => surface.state.canGoBack === true;
    element.canGoForward = () => surface.state.canGoForward === true;
    element.goBack = () => sendCommand(surface, "go-back");
    element.goForward = () => sendCommand(surface, "go-forward");
    element.reload = () => sendCommand(surface, "reload");
    element.stop = () => sendCommand(surface, "stop");
    element.getWebContentsId = () => -1;
    element.executeJavaScript = async () => undefined;
    element.send = () => {};
    element.destroy = () => {
      if (!surface.key) return;
      surfaces.delete(surface.key);
      transport.send({
        type: "browser-surface-unsubscribe",
        conversationId: surface.conversationId,
        browserTabId: surface.browserTabId,
      });
      surface.key = null;
    };

    element.addEventListener("pointerdown", (event) => {
      element.focus();
      element.setPointerCapture?.(event.pointerId);
      sendCommand(surface, "input", {
        input: {
          type: "mouseDown",
          button: buttonName(event.button),
          clickCount: event.detail || 1,
          ...pointerPosition(element, event),
        },
      });
      event.preventDefault();
    });
    element.addEventListener("pointermove", (event) => {
      sendCommand(surface, "input", {
        input: {
          type: "mouseMove",
          ...pointerPosition(element, event),
        },
      });
    });
    element.addEventListener("pointerup", (event) => {
      sendCommand(surface, "input", {
        input: {
          type: "mouseUp",
          button: buttonName(event.button),
          clickCount: event.detail || 1,
          ...pointerPosition(element, event),
        },
      });
      event.preventDefault();
    });
    element.addEventListener(
      "wheel",
      (event) => {
        sendCommand(surface, "input", {
          input: {
            type: "mouseWheel",
            deltaX: -event.deltaX,
            deltaY: -event.deltaY,
            ...pointerPosition(element, event),
          },
        });
        event.preventDefault();
      },
      { passive: false },
    );
    element.addEventListener("keydown", (event) => {
      sendCommand(surface, "input", {
        input: { type: "keyDown", keyCode: event.key },
      });
      if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) {
        sendCommand(surface, "input", {
          input: { type: "char", keyCode: event.key },
        });
      }
      event.preventDefault();
      event.stopPropagation();
    });
    element.addEventListener("keyup", (event) => {
      sendCommand(surface, "input", {
        input: { type: "keyUp", keyCode: event.key },
      });
      event.preventDefault();
      event.stopPropagation();
    });
    element.addEventListener("focus", () => sendCommand(surface, "focus"));

    return element;
  }

  function browserSurfaceHost() {
    const root = document.querySelector(
      "[data-browser-sidebar-primary-focus-target]",
    );
    return root?.lastElementChild || null;
  }

  function syncBrowserChrome(surface) {
    const root = document.querySelector(
      "[data-browser-sidebar-primary-focus-target]",
    );
    if (!root) return;
    const address = root.querySelector("[data-browser-sidebar-address-input]");
    if (address && document.activeElement !== address) {
      address.value = browserDisplayUrl(surface.state.url);
    }
    const back = root.querySelector('button[aria-label="Back"]');
    const forward = root.querySelector('button[aria-label="Next"]');
    if (back) back.disabled = surface.state.canGoBack !== true;
    if (forward) forward.disabled = surface.state.canGoForward !== true;
    const tabLabel = document.querySelector(
      '[role="tab"][aria-selected="true"] > span:last-child > span',
    );
    if (tabLabel) {
      tabLabel.textContent =
        browserDisplayUrl(surface.state.url).split("/")[0] ||
        surface.state.title ||
        "New tab";
    }
  }

  function ensureSidebarSurface(payload) {
    if (!payload?.conversationId || !payload?.browserTabId) return null;
    latestSidebarSync = payload;
    const key = surfaceKey(payload.conversationId, payload.browserTabId);
    let surface = surfaces.get(key);
    const host = browserSurfaceHost();
    if (!host) return null;
    if (!surface) {
      surface = mountingSurfaces.get(key);
      if (!surface) {
        const element = createWebview(document);
        surface = elementSurfaces.get(element);
        mountingSurfaces.set(key, surface);
        element.setAttribute(conversationAttribute, payload.conversationId);
        element.setAttribute(tabAttribute, payload.browserTabId);
        host.append(element);
      }
    } else if (!surface.element.isConnected) {
      host.append(surface.element);
    }
    const active = payload.presented !== false && payload.visible !== false;
    for (const candidate of surfaces.values()) {
      candidate.element.style.display =
        candidate.element === surface.element && active ? "block" : "none";
    }
    surface.element.style.display = active ? "block" : "none";
    const pending = pendingSidebarCommands.get(payload.conversationId);
    if (pending) {
      pendingSidebarCommands.delete(payload.conversationId);
      queueMicrotask(() => handleSidebarCommand(pending));
    }
    return surface;
  }

  Document.prototype.createElement = function createElement(name, options) {
    if (String(name).toLowerCase() === "webview") {
      return createWebview(this);
    }
    return nativeCreateElement.call(this, name, options);
  };

  for (const eventName of ["pointerdown", "pointermove", "pointerup"]) {
    document.addEventListener(
      eventName,
      (event) => {
        const surface = surfaceAtPoint(event.clientX, event.clientY);
        if (!surface || surface.element.contains(event.target)) return;
        if (eventName === "pointerdown") {
          keyboardSurface = surface;
          surface.element.focus();
        }
        sendCommand(surface, "input", {
          input: {
            type:
              eventName === "pointerdown"
                ? "mouseDown"
                : eventName === "pointerup"
                  ? "mouseUp"
                  : "mouseMove",
            ...(eventName === "pointermove"
              ? {}
              : {
                  button: buttonName(event.button),
                  clickCount: event.detail || 1,
                }),
            ...pointerPosition(surface.element, event),
          },
        });
      },
      true,
    );
  }

  document.addEventListener(
    "wheel",
    (event) => {
      const surface = surfaceAtPoint(event.clientX, event.clientY);
      if (!surface || surface.element.contains(event.target)) return;
      sendCommand(surface, "input", {
        input: {
          type: "mouseWheel",
          deltaX: -event.deltaX,
          deltaY: -event.deltaY,
          ...pointerPosition(surface.element, event),
        },
      });
      event.preventDefault();
    },
    { capture: true, passive: false },
  );

  document.addEventListener(
    "click",
    (event) => {
      const button = event.target.closest?.("button");
      const root = button?.closest?.(
        "[data-browser-sidebar-primary-focus-target]",
      );
      const surface = latestSidebarSync
        ? findSurface(
            latestSidebarSync.conversationId,
            latestSidebarSync.browserTabId,
          )
        : null;
      if (!root || !surface) return;
      const command = {
        Back: "go-back",
        Next: "go-forward",
        "Reload page": "reload",
        "Stop loading": "stop",
      }[button.getAttribute("aria-label") || button.getAttribute("title")];
      if (!command) return;
      sendCommand(surface, command);
      event.preventDefault();
      event.stopImmediatePropagation();
    },
    true,
  );

  for (const eventName of ["keydown", "keyup"]) {
    document.addEventListener(
      eventName,
      (event) => {
        if (
          !keyboardSurface ||
          keyboardSurface.element.contains(event.target) ||
          event.target instanceof HTMLInputElement ||
          event.target instanceof HTMLTextAreaElement ||
          event.target?.isContentEditable
        ) {
          return;
        }
        sendCommand(keyboardSurface, "input", {
          input: {
            type: eventName === "keydown" ? "keyDown" : "keyUp",
            keyCode: event.key,
          },
        });
        if (
          eventName === "keydown" &&
          event.key.length === 1 &&
          !event.ctrlKey &&
          !event.metaKey
        ) {
          sendCommand(keyboardSurface, "input", {
            input: { type: "char", keyCode: event.key },
          });
        }
        event.preventDefault();
        event.stopPropagation();
      },
      true,
    );
  }

  transport.onControl((message) => {
    if (
      message.action !== "browser-surface-state" &&
      message.action !== "browser-surface-frame"
    ) {
      return;
    }
    const key = surfaceKey(message.conversationId, message.browserTabId);
    const surface = key ? surfaces.get(key) : null;
    if (!surface) return;
    surface.generation = message.generation || surface.generation;
    if (message.action === "browser-surface-state") {
      const wasLoading = surface.state.isLoading === true;
      surface.state = message.state || {};
      syncBrowserChrome(surface);
      if (
        normalizeUrl(surface.pendingNavigation) ===
        normalizeUrl(surface.state.url)
      ) {
        surface.pendingNavigation = null;
        surface.desiredUrl = null;
        surface.initialUrl = null;
        clearTimeout(surface.navigationTimer);
      }
      reconcileNavigation(surface);
      if (!wasLoading && surface.state.isLoading) {
        dispatch(surface.element, "did-start-loading");
      }
      if (wasLoading && !surface.state.isLoading) {
        dispatch(surface.element, "did-stop-loading");
      }
      if (surface.state.url) {
        dispatch(surface.element, "did-navigate", {
          isMainFrame: true,
          url: surface.state.url,
        });
      }
      if (surface.state.title) {
        dispatch(surface.element, "page-title-updated", {
          explicitSet: true,
          title: surface.state.title,
        });
      }
      dispatch(surface.element, "did-attach");
      return;
    }
    const frame = message.frame;
    if (frame?.data && frame?.mimeType) {
      surface.image.src = `data:${frame.mimeType};base64,${frame.data}`;
      dispatch(surface.element, "paint");
    }
  });

  function handleSidebarCommand(message) {
    const surface = findSurface(message.conversationId, message.browserTabId);
    if (!surface) {
      pendingSidebarCommands.set(message.conversationId, message);
      return;
    }
    const command = message.command || {};
    switch (command.type) {
      case "navigate":
        surface.desiredUrl = command.url;
        surface.pendingNavigation = command.url;
        sendCommand(surface, "navigate", { url: command.url });
        break;
      case "go-back":
        sendCommand(surface, "go-back");
        break;
      case "go-forward":
        sendCommand(surface, "go-forward");
        break;
      case "reload":
        sendCommand(surface, "reload");
        break;
      case "stop":
        sendCommand(surface, "stop");
        break;
      case "reset":
        sendCommand(surface, "navigate", { url: "about:blank" });
        break;
      case "scroll":
        sendCommand(surface, "input", {
          input: {
            type: "mouseWheel",
            deltaX: command.scroll?.deltaX || 0,
            deltaY: command.scroll?.deltaY || 0,
            xRatio: 0.5,
            yRatio: 0.5,
          },
        });
        break;
    }
  }

  transport.onMessageFromView((message) => {
    if (message?.type === "browser-sidebar-sync") {
      ensureSidebarSurface(message.payload);
      return;
    }
    if (message?.type === "browser-sidebar-command") {
      handleSidebarCommand(message);
    }
  });

  new MutationObserver(() => {
    if (latestSidebarSync) ensureSidebarSurface(latestSidebarSync);
  }).observe(document.documentElement, { childList: true, subtree: true });

  window.addEventListener("message", (event) => {
    const message = event.data;
    if (
      message?.type !== "browser-sidebar-state" ||
      !message.conversationId ||
      !message.browserTabId
    ) {
      return;
    }
    const key = surfaceKey(message.conversationId, message.browserTabId);
    officialSnapshots.set(key, message.snapshot || {});
    const surface = surfaces.get(key);
    if (
      surface &&
      message.snapshot?.url &&
      !surface.state.url &&
      normalizeUrl(message.snapshot.url) !==
        normalizeUrl(surface.lastOfficialUrl)
    ) {
      surface.lastOfficialUrl = message.snapshot.url;
      surface.desiredUrl = message.snapshot.url;
      reconcileNavigation(surface);
    }
  });
})();
