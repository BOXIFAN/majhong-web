/* BRML App Service Worker：只接管 /app/ 作用域，静态资源缓存优先，页面离线兜底。 */

// 改动静态资源后把版本号 +1，客户端下次打开即会换新缓存。
const CACHE = "brml-app-v3";
const PRECACHE = [
  "/app",
  "/static/app-pwa.css",
  "/static/app-pwa.js",
  "/static/web_logo.jpg",
  "/static/pwa/icon-192.png",
  "/static/pwa/icon-512.png",
  "/static/pwa/icon-maskable-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

async function cachePut(request, response) {
  if (response && response.ok) {
    const cache = await caches.open(CACHE);
    cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  // 静态资源：缓存优先，避免每次切换页面都重新下载。
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((response) => cachePut(request, response)))
    );
    return;
  }

  // App 页面：网络优先，断网时回退到上次缓存的页面。
  if (url.pathname === "/app" || url.pathname.startsWith("/app/")) {
    event.respondWith(
      fetch(request)
        .then((response) => cachePut(request, response))
        .catch(() => caches.match(request).then((hit) => hit || caches.match("/app")))
    );
  }
});
