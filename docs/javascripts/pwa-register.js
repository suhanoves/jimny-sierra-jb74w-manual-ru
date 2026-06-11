(() => {
  if (!("serviceWorker" in navigator)) return;
  if (!["http:", "https:"].includes(window.location.protocol)) return;

  const base = window.__md_scope || new URL(".", window.location.href);

  window.addEventListener("load", () => {
    navigator.serviceWorker.register(new URL("sw.js", base), {
      scope: base.pathname,
    }).catch(() => {});
  });
})();
