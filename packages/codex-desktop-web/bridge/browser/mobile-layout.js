(() => {
  const mobile = matchMedia('(max-width: 767px), (pointer: coarse) and (max-height: 600px)');
  const root = document.documentElement;
  let sidebar;
  let backdrop;
  let coveredSurface;
  let wasInert = false;
  let returnFocus;

  function closeSidebar() {
    const toggle = [...document.querySelectorAll('button[aria-controls="app-shell-sidebar"][aria-expanded="true"]')]
      .find((button) => button.getClientRects().length > 0);
    toggle?.click();
  }

  function updateViewport() {
    root.style.setProperty('--codex-web-viewport-height',
      `${Math.round(window.visualViewport?.height || innerHeight)}px`);
  }

  function updateSidebar() {
    const open = mobile.matches && sidebar?.getBoundingClientRect().width > 20;
    root.toggleAttribute('data-codex-web-sidebar-open', Boolean(open));
    if (backdrop) backdrop.hidden = !open;
    const surface = open ? document.querySelector('[data-app-shell-main-surface]') : null;
    if (surface !== coveredSurface) {
      if (coveredSurface) coveredSurface.inert = wasInert;
      coveredSurface = surface;
      if (surface) {
        wasInert = surface.inert;
        returnFocus = document.activeElement;
        surface.inert = true;
        sidebar.querySelector('button, [tabindex="0"], a[href]')?.focus();
      } else if (returnFocus?.isConnected) {
        returnFocus.focus();
        returnFocus = null;
      }
    }
  }

  const observer = new ResizeObserver(updateSidebar);
  function findSidebar() {
    const next = document.querySelector('.app-shell-left-panel');
    if (next === sidebar) { updateSidebar(); return; }
    if (sidebar) observer.unobserve(sidebar);
    sidebar = next;
    if (sidebar) observer.observe(sidebar);
    if (!backdrop && sidebar) {
      backdrop = document.createElement('button');
      backdrop.type = 'button';
      backdrop.setAttribute('aria-label', 'Close sidebar');
      backdrop.dataset.codexWebSidebarBackdrop = '';
      backdrop.hidden = true;
      backdrop.onclick = closeSidebar;
    }
    if (sidebar && backdrop) sidebar.parentElement.append(backdrop);
    updateSidebar();
  }

  document.addEventListener('click', (event) => {
    if (!mobile.matches || !sidebar?.contains(event.target)) return;
    if (event.target.closest('[data-app-action-sidebar-thread-row]') ||
        event.target.closest('nav button.sidebar-item')) {
      // Let upstream select the conversation before closing its drawer.
      setTimeout(closeSidebar, 0);
    }
  });
  new MutationObserver(findSidebar).observe(root, { childList: true, subtree: true });
  window.visualViewport?.addEventListener('resize', updateViewport);
  window.addEventListener('resize', updateViewport);
  mobile.addEventListener('change', updateSidebar);
  updateViewport();
  findSidebar();

  const style = document.createElement('style');
  style.textContent = `
    [data-codex-web-sidebar-backdrop] { display: none; }
    @media (max-width: 767px), (pointer: coarse) and (max-height: 600px) {
      html, body, #root {
        height: var(--codex-web-viewport-height, 100dvh) !important;
        min-height: 0 !important;
        max-height: var(--codex-web-viewport-height, 100dvh) !important;
      }
      body { overflow: hidden; }
      #root > [style*="--codex-window-zoom"] {
        height: calc(var(--codex-web-viewport-height, 100dvh) / var(--codex-window-zoom, 1)) !important;
      }
      .app-shell-left-panel {
        position: absolute !important;
        inset-block: 0;
        left: 0;
        z-index: 41;
        background: var(--color-background-elevated-primary-opaque, #202020);
      }
      [data-app-shell-main-surface] { width: 100% !important; }
      [data-codex-web-sidebar-backdrop]:not([hidden]) {
        display: block;
        position: fixed;
        inset: 0;
        z-index: 40;
        border: 0;
        padding: 0;
        background: #0006;
      }
      [data-codex-web-dialog] {
        height: var(--codex-web-viewport-height, 100dvh) !important;
      }
      [data-codex-web-dialog] > div {
        max-height: calc(var(--codex-web-viewport-height, 100dvh) - 32px);
      }
      [class*="home-main-content"] [class~="min-h-fit"][class~="grow"] {
        min-height: 0 !important;
        flex-shrink: 1;
      }
      [class*="home-main-content"] [class~="grow"]:has([data-codex-composer-root]) {
        flex-grow: 0;
        flex-shrink: 0;
        flex-basis: auto;
      }
      [class*="home-main-content"] [class~="items-end"][class~="grow"] {
        overflow: auto;
        padding-bottom: 16px;
      }
      [class*="home-main-content"] :has(> [data-home-ambient-suggestions]) {
        margin-top: 0 !important;
      }
    }
  `;
  document.head.append(style);
})();
