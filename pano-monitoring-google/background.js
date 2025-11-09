function extractPanoramaData(url) {
  /*
  https://lh3.googleusercontent.com/p/AF1QipMLd8Z64bzfWQUBYwI2fUegzvMN2ovOygu8F-lY=x19-y7-z5-k-no
  */
  const urlParams = new URLSearchParams(url);
  const panoramaId = urlParams.get('panoid');
  const x = urlParams.get('x');
  const y = urlParams.get('y');
  const zoom = urlParams.get('zoom');
  const tileName = `${zoom}.${x}.${y}`;

  return {panoramaId, tileName};
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
        const response = await fetch('http://127.0.0.1:5000/aa/google-panorama', {
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
  { urls: ["https://streetviewpixels-pa.googleapis.com/v1/tile?*"] }
);