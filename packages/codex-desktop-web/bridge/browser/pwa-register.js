(() => {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/__bridge/sw.js", { scope: "/" }).catch(() => {});
  });
})();
