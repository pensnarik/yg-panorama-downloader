// Функция для извлечения данных из URL
function extractUrlData() {
  const urlParams = new URLSearchParams(window.location.href);
  const panoramaPoint = urlParams.get('panorama[point]');
  const panoramaIdFromURL = urlParams.get('panorama[id]');

  return {
    panoramaIdFromURL
  };
}

function extractCoords(url) {
  // Ищем часть строки после "@" и до следующего "/"
  console.log("Looking for COORDS in URL", url);

  const coordinatesMatch = url.match(/@([-\d.]+),([-\d.]+)/);

  if (coordinatesMatch) {
    const latitude = coordinatesMatch[1];  // Широта
    const longitude = coordinatesMatch[2]; // Долгота
    console.log("Широта:", latitude);
    console.log("Долгота:", longitude);
    return `${longitude},${latitude}`
  } else {
    console.log("Координаты не найдены в ссылке.");
    return null;
  }
}

// Функция для извлечения даты
function extractDate() {
  const dateElement = document.querySelector("div.mqX5ad");
  if (dateElement) {
    return dateElement.textContent.trim();
  }


  return "unknown"; // Если элемент не найден
}

function extractView() {
  const viewElement = document.querySelector("h1.r4sJF");

  if (viewElement) {
    return viewElement.textContent.trim();
  }

  return "unknown";
}


// Слушаем запросы от фонового скрипта
browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log("Listener getData() in content.js", message);

  if (message.type === "getData") {
    const urlData = extractUrlData();
    const panoramaPoint = extractCoords(window.location.href);
    const year = extractDate();
    const view = extractView();

    console.log("Date from content: ", year);

    const fullData = {
      ...urlData,
      year,
      view,
      panoramaPoint
    };

    console.log("Sending data to background script:", fullData);
    sendResponse(fullData); // Отправляем данные обратно в фоновый скрипт
  }
});