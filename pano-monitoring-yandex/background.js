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