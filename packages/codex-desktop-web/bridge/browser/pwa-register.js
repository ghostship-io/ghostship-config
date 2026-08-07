(() => {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;

  const DISMISSED_KEY = "codex:pwa-install-dismissed";
  let installEvent = null;
  let installPrompt = null;

  function installDismissed() {
    try {
      return localStorage.getItem(DISMISSED_KEY) === "true";
    } catch {
      return false;
    }
  }

  function dismissInstallPrompt() {
    try {
      localStorage.setItem(DISMISSED_KEY, "true");
    } catch {
      // Keep the current page dismissed when persistent browser storage is unavailable.
    }
  }

  function isStandalone() {
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true
    );
  }

  function removeInstallPrompt() {
    installPrompt?.remove();
    installPrompt = null;
  }

  function positionInstallPrompt() {
    if (!installPrompt) return;
    const notificationPrompt = document.querySelector(
      "[data-codex-notification-prompt]",
    );
    installPrompt.style.top = notificationPrompt
      ? `${Math.ceil(notificationPrompt.getBoundingClientRect().bottom + 12)}px`
      : "max(48px, calc(env(safe-area-inset-top) + 12px))";
  }

  function installButton(label, primary = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    Object.assign(button.style, {
      alignItems: "center",
      background: primary
        ? "var(--color-token-text-primary, #fcfcfc)"
        : "transparent",
      border: primary
        ? "1px solid var(--color-token-text-primary, #fcfcfc)"
        : "1px solid var(--color-token-border-default, rgba(252, 252, 252, 0.16))",
      borderRadius: "9999px",
      color: primary
        ? "var(--color-token-button-foreground, #090909)"
        : "var(--color-token-text-primary, #fcfcfc)",
      cursor: "pointer",
      display: "inline-flex",
      font: "inherit",
      fontWeight: "500",
      justifyContent: "center",
      minHeight: "34px",
      padding: "6px 14px",
      whiteSpace: "nowrap",
    });
    return button;
  }

  function showInstallPrompt() {
    if (
      installPrompt ||
      !installEvent ||
      isStandalone() ||
      installDismissed()
    ) {
      return;
    }

    const prompt = document.createElement("aside");
    prompt.dataset.codexInstallPrompt = "";
    prompt.setAttribute("aria-label", "Install Codex");
    prompt.setAttribute("aria-live", "polite");
    prompt.setAttribute("role", "status");
    Object.assign(prompt.style, {
      alignItems: "center",
      background:
        "var(--color-background-elevated-primary-opaque, rgb(47, 47, 47))",
      border:
        "1px solid var(--color-token-border-default, rgba(252, 252, 252, 0.16))",
      borderRadius: "14px",
      boxShadow: "var(--shadow-2xl, 0 16px 32px -8px rgba(0, 0, 0, 0.4))",
      color: "var(--color-token-text-primary, #fcfcfc)",
      display: "flex",
      flexWrap: "wrap",
      fontFamily: "inherit",
      fontSize: "14px",
      gap: "12px",
      justifyContent: "space-between",
      left: "50%",
      lineHeight: "1.4",
      maxWidth: "min(520px, calc(100vw - 24px))",
      padding: "12px 14px",
      position: "fixed",
      transform: "translateX(-50%)",
      width: "max-content",
      zIndex: "2147483000",
    });

    const description = document.createElement("span");
    description.textContent = "Install Codex for quicker access";
    description.style.flex = "1 1 180px";

    const actions = document.createElement("span");
    Object.assign(actions.style, {
      display: "flex",
      flex: "0 0 auto",
      gap: "8px",
    });
    const dismiss = installButton("Dismiss");
    const install = installButton("Install", true);

    dismiss.addEventListener("click", () => {
      dismissInstallPrompt();
      installEvent = null;
      removeInstallPrompt();
    });
    install.addEventListener("click", async () => {
      const event = installEvent;
      if (!event) return;
      installEvent = null;
      document.documentElement.dataset.codexInstallPrompt = "requested";
      removeInstallPrompt();
      try {
        await event.prompt();
        await event.userChoice;
      } catch {
        document.documentElement.dataset.codexInstallPrompt = "failed";
      }
    });

    actions.append(dismiss, install);
    prompt.append(description, actions);
    document.body.append(prompt);
    installPrompt = prompt;
    positionInstallPrompt();
  }

  new MutationObserver(() => {
    if (installPrompt && !installPrompt.isConnected) {
      installPrompt = null;
    }
    showInstallPrompt();
    positionInstallPrompt();
  }).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });

  window.addEventListener("beforeinstallprompt", (event) => {
    if (typeof event.prompt !== "function" || isStandalone()) return;
    event.preventDefault();
    installEvent = event;
    showInstallPrompt();
  });

  window.addEventListener("appinstalled", () => {
    installEvent = null;
    removeInstallPrompt();
    document.documentElement.dataset.codexInstallPrompt = "installed";
  });

  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/__bridge/sw.js", { scope: "/" }).catch(() => {});
  });
})();
