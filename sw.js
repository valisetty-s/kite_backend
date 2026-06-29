// Service worker for The Morning Ledger
// Caches the app shell so it opens instantly even on a flaky connection.
// News fetches always go to the network (never cached) since freshness matters.

const CACHE_NAME = 'morning-ledger-v17';
const SHELL_FILES = [
  './index.html',
  './app.js',
  './manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = event.request.url;

  // Only ever intercept GET requests for the app's own static shell files.
  // Everything else — and this is the actual bug fixed in v14 — must pass
  // straight through untouched.
  //
  // What went wrong before: this handler intercepted EVERY fetch the page
  // made, including POST requests to the backend (/api/kite/exchange) and
  // GET requests to it (/api/quotes, /api/news). The exclusion list only
  // named the old news proxies (news.google.com, allorigins.win,
  // codetabs.com) — it never excluded calls to the backend itself. Running
  // a POST request through caches.match() / response.clone() here is
  // exactly the kind of thing that can cause a request to be duplicated or
  // its body mishandled, which matches the double /api/kite/exchange call
  // (one real, one empty) seen in testing. Restricting this handler to
  // GET-only, same-origin, static-file requests removes the whole category
  // of risk rather than trying to special-case every backend route by name.
  if (event.request.method !== 'GET') {
    return; // let it go straight to the network, completely untouched
  }
  if (!url.startsWith(self.location.origin)) {
    return; // any cross-origin request (backend API, news, anything) — untouched
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request).then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      }).catch(() => cached);
    })
  );
});
