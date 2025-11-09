// Функция для извлечения данных из URL
function extractUrlData() {
  const urlParams = new URLSearchParams(window.location.search);
  const panoramaPoint = urlParams.get('panorama[point]');
  const panoramaIdFromURL = urlParams.get('panorama[id]');

  return {
    panoramaPoint,
    panoramaIdFromURL
  };
}

// Функция для извлечения года
function extractYear() {
  const yearElement = document.querySelector(".panorama-controls-view__history .button__text");
  if (yearElement) {
    return yearElement.textContent.trim(); // Убираем лишние пробелы
  }
  return "unknown"; // Если элемент не найден
}

function extractView() {
  const viewElement = document.querySelector(".panorama-player-view__name");

  if (viewElement) {
    return viewElement.textContent.trim();
  }
  return "unknown";
}


// Слушаем запросы от фонового скрипта
browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "getData") {
    const urlData = extractUrlData();
    const year = extractYear();
    const view = extractView();

    const fullData = {
      ...urlData,
      year,
      view
    };

    console.log("Sending data to background script:", fullData);
    sendResponse(fullData); // Отправляем данные обратно в фоновый скрипт
  }
});