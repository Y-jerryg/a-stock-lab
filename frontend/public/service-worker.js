// Cache only the static shell. Result JSON and API responses always use the network.
const CACHE = 'a-stock-lab-shell-v1';
const ROOT = new URL('./', self.location.href).href;
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll([ROOT, ROOT + 'trend-icon.svg'])),
  );
});
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith('a-stock-lab-shell-') && key !== CACHE)
            .map((key) => caches.delete(key)),
        ),
      ),
  );
});
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (
    request.method !== 'GET' ||
    url.origin !== self.location.origin ||
    !request.url.startsWith(ROOT) ||
    url.pathname.includes('/api/')
  )
    return;
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request, { cache: 'no-store' }).catch(
        async () => (await caches.match(ROOT)) || Response.error(),
      ),
    );
  } else if (url.pathname.startsWith(new URL('assets/', ROOT).pathname)) {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const saved = await cache.match(request);
        if (saved && !saved.headers.get('content-type')?.includes('text/html')) return saved;
        const response = await fetch(request);
        if (response.ok && !response.headers.get('content-type')?.includes('text/html'))
          await cache.put(request, response.clone());
        return response;
      }),
    );
  }
});
