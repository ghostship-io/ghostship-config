if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/__t3_pwa/sw.js", { scope: "/", updateViaCache: "none" })
      .catch(() => console.warn("T3 Code offline screen is unavailable"));
  }, { once: true });
}
