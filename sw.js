// Market Terminal service worker.
//
// index.html (and any navigation): NETWORK-FIRST with cache fallback. The old
// cache-first shell meant an edited index.html never reached an installed copy
// until CACHE was hand-bumped, so code changes appeared to do nothing.
// Static assets (icons, svg, manifest): stale-while-revalidate — instant, self-healing.
// data.json / config.json: network-first with cache fallback, so the last
// snapshot still renders offline.
const CACHE = "terminal-v4";
const SHELL = ["./", "./index.html", "./manifest.json", "./guilloche.svg",
               "./icons/icon-192.png", "./icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

const put = (req, res) => {
  const copy = res.clone();
  caches.open(CACHE).then((c) => c.put(req, copy));
  return res;
};

const networkFirst = (req) =>
  fetch(req).then((res) => put(req, res)).catch(() => caches.match(req));

const staleWhileRevalidate = (req) =>
  caches.match(req).then((hit) => {
    const fresh = fetch(req).then((res) => put(req, res)).catch(() => hit);
    return hit || fresh;
  });

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  const isDoc = e.request.mode === "navigate" ||
                url.pathname.endsWith("/") ||
                url.pathname.endsWith("index.html");
  const isData = url.pathname.endsWith("data.json") || url.pathname.endsWith("config.json");

  e.respondWith(isDoc || isData ? networkFirst(e.request) : staleWhileRevalidate(e.request));
});
