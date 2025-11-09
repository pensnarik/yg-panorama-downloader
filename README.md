Yandex & Google panorama downloader
===================================

Проект содержит:

1. Расширение для браузера `pano-monitoring-google`
2. Расширение для браузера `pano-monitoring-yandex`
3. Flask сервер `monitoring-server`
4. Скрипт для скачивания и склейки панорам [download_in_realtime.py](download_in_realtime.py)

## Установка и запуск

Для установки необходимо:

1. Подготовить базу данных PostgreSQL (скрипт [V001__Initial_schema.sql](db/migrations/V001__Initial_schema.sql))
2. Активировать виртуальное окружение:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Запустить сервер [monitoring-server](monitoring-server), должен быть запущен
   на http://127.0.0.1:5000.
4. Установить расширение в браузер (в Firefox: about:debugging -> This Firefox
   -> Load temporary addon)

## Как это работает?

Расширение для браузера перехватывает запросы от Yandex или Google, извлекает
данные о текущей панораме из содержимого страницы и сохраняет их в базе данных
пользователя (HTTP endpoint http://127.0.0.1:5000/aa/yandex-panorama или 
http://127.0.0.1:5000/aa/google-panorama).

Запущенный скрипт `download_in_real_time.py` ищет в таблице `panorama_log`
записи для панорам, которые не были скачаны и скачивает их потайлово, после
этого запускает скрипт `merge.py` для склейки панорамы. Итоговые изображения
сохраняются в директорию `panos`.

В принципе, для скачивания и склейки панорам достаточно скриптов `pano.py` (`pano-google.py`)
и `merge.py`, но для этого нужно знать ID панорамы. Также скрипт `merge.py`
добавляет на панораму информацию о координатах, месте, даты и времени съёмки -
эта информация извлекается соотвутствующим плагином для браузера.