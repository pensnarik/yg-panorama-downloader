// Metadata is saved independently of tile requests: cached tiles and quick
// navigation must not associate an image with another panorama's DOM state.
const METADATA_ENDPOINT = 'http://127.0.0.1:5000/aa/yandex-panorama-metadata';
const OUTBOX_PREFIX = 'panorama-metadata:';
let storageWork = Promise.resolve();
let flushing = false;

function serializeStorage(work) {
  storageWork = storageWork.then(work).catch(error => {
    console.error('Panorama metadata:', error);
  });
  return storageWork;
}

async function flushMetadata() {
  if (flushing) return;
  flushing = true;
  try {
    const pending = await browser.storage.local.get(null);
    for (const [key, capture] of Object.entries(pending)) {
      if (!key.startsWith(OUTBOX_PREFIX)) continue;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const response = await fetch(METADATA_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(capture),
          signal: controller.signal
        });
        if (!response.ok) {
          console.warn(`Metadata server returned ${response.status}; keeping ${capture.imageId}`);
          if (response.status >= 500) break;
          continue; // A rejected record must not block the rest of the outbox.
        }
        const result = await response.json();
        if (result.status !== 'ok' || result.imageId !== capture.imageId) {
          throw new Error('Metadata server did not acknowledge this image');
        }
        if (result.geometryFieldsPresent === false) {
          console.warn('Archived metadata has missing geometry fields:', result.missingFields);
        }
        await serializeStorage(async () => {
          const current = (await browser.storage.local.get(key))[key];
          // A newer response may arrive while this POST is in flight.
          if (JSON.stringify(current) === JSON.stringify(capture)) {
            await browser.storage.local.remove(key);
          }
        });
      } catch (error) {
        console.warn('Metadata remains in the Firefox outbox; retry in one minute.', error);
        break;
      } finally {
        clearTimeout(timeout);
      }
    }
  } finally {
    flushing = false;
  }
}

function enqueueMetadata(capture) {
  return serializeStorage(async () => {
    const key = OUTBOX_PREFIX + capture.imageId;
    const previous = (await browser.storage.local.get(key))[key];
    if (!previous || previous.capturedAt <= capture.capturedAt) {
      await browser.storage.local.set({ [key]: capture });
    }
  }).then(() => flushMetadata()).catch(error => console.error('Metadata outbox:', error));
}

browser.alarms.create('retry-panorama-metadata', { periodInMinutes: 1 });
browser.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'retry-panorama-metadata') {
    flushMetadata().catch(error => console.error('Metadata outbox:', error));
  }
});
flushMetadata().catch(error => console.error('Metadata outbox:', error));

browser.webRequest.onBeforeRequest.addListener(details => {
  // Do not capture unrelated traffic or initiate additional Yandex requests.
  if (details.tabId < 0) return;
  const capturedAt = new Date().toISOString();
  let filter;
  try {
    filter = browser.webRequest.filterResponseData(details.requestId);
  } catch (error) {
    console.error('Cannot capture panorama response:', error);
    return;
  }
  const decoder = new TextDecoder('utf-8');
  let text = '';
  let bytes = 0;
  filter.ondata = event => {
    // Always forward original bytes immediately; parsing cannot break the map.
    filter.write(event.data);
    bytes += event.data.byteLength;
    if (bytes > 16 * 1024 * 1024) {
      console.error('Panorama response exceeds 16 MiB; capture skipped, not truncated.');
      text = '';
      filter.disconnect();
      return;
    }
    text += decoder.decode(event.data, { stream: true });
  };
  filter.onstop = () => {
    filter.close();
    try {
      text += decoder.decode();
      const capture = PanoramaMetadata.makeCapture(
        PanoramaMetadata.parseResponse(text), details.url, capturedAt
      );
      enqueueMetadata(capture);
    } catch (error) {
      console.warn('Panorama metadata response was not saved:', error);
    }
  };
  filter.onerror = () => {
    // Firefox owns stream recovery after a StreamFilter error.
    console.warn('Panorama response stream failed:', filter.error);
  };
}, { urls: ['https://api-maps.yandex.ru/services/panoramas/*'] }, ['blocking']);

function extractPanoramaData(url) {
  const regex = /https:\/\/pano\.maps\.yandex\.net\/([^\/]+)\/([^\/]+)/;
  const match = url.match(regex);
  if (match) {
    return {
      panoramaId: match[1],
      tileName: match[2]
    };
  }
  return null;
}

browser.webRequest.onBeforeRequest.addListener(
  async function(details) {
    const panoramaData = extractPanoramaData(details.url);
    if (panoramaData) {
      console.log("Extracted panorama data:", panoramaData);

      // Запрашиваем данные у контент-скрипта
      try {
        const urlData = await browser.tabs.sendMessage(details.tabId, { type: "getData" });
        console.log("Received URL data from content script:", urlData);

        // Объединяем данные
        const fullData = {
          ...urlData,
          ...panoramaData
        };

        console.log("Sending data to server:", fullData);

        // Отправляем данные на сервер
        const response = await fetch('http://127.0.0.1:5000/aa/yandex-panorama', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(fullData)
        });

        if (!response.ok) {
          console.error('Failed to send data to server. Status:', response.status);
        } else {
          console.log('Data sent successfully');
        }
      } catch (error) {
        console.error('Error sending data to server:', error);
      }
    }
  },
  { urls: ["https://pano.maps.yandex.net/*"] }
);
