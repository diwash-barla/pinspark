const CACHE_NAME = 'pinspark-v1';
const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/manifest.json'
];

// इंस्टॉल होने पर UI फाइल्स को कैश कर लो
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
});

self.addEventListener('fetch', event => {
    // API कॉल्स को कभी कैश नहीं करना है (वे हमेशा लाइव Pinterest सर्वर से आएंगी)
    if (event.request.url.includes('/api/')) {
        event.respondWith(fetch(event.request));
        return;
    }
    
    // बाकी चीज़ों (HTML/JS/CSS) के लिए पहले कैश चेक करो, फिर नेटवर्क
    event.respondWith(
        caches.match(event.request).then(response => {
            return response || fetch(event.request);
        })
    );
});
