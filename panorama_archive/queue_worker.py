#!/usr/bin/env python3
"""Fetch metadata, download tiles and finish durable jobs with a renewable lease."""
from threading import Event, Thread
from pathlib import Path
from .tile_geometry import TileGeometry
import subprocess
import psycopg
import requests
from .logging import DownloadLog
from .queue import DownloadQueue
from .remote_metadata import RemoteMetadata


class QueueLease:
    def __init__(self, queue, job):
        self.queue, self.job = queue, job
        self.stopped = Event()
        self.thread = Thread(target=self._renew, daemon=True, name='download-lease')

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *arguments):
        self.stopped.set()
        self.thread.join(timeout=10)

    def _renew(self):
        while not self.stopped.wait(30):
            try:
                if not self.queue.heartbeat(self.job):
                    return
            except psycopg.Error:
                DownloadLog.write('Не удалось продлить аренду задания очереди.', flush=True)


class QueueWorker:
    def __init__(self, monitor):
        self.monitor, self.queue = monitor, DownloadQueue()

    def process(self):
        job = self.queue.claim()
        if job is None:
            return False
        with QueueLease(self.queue, job):
            self._process(job)
        return True

    def _process(self, job):
        try:
            self._download(job)
        except (requests.RequestException, ValueError, OSError, subprocess.CalledProcessError, psycopg.Error) as error:
            message = self._message(error)
            self.queue.finish(job, message)
            DownloadLog.write(f"{job['panorama_id']}: {message}", flush=True)
        else:
            self.queue.finish(job)

    def _download(self, job):
        DownloadLog.write(f"Очередь: получение метаданных {job['panorama_id']}", flush=True)
        metadata = RemoteMetadata().fetch(job['panorama_id'])
        image_id = RemoteMetadata.save(metadata)
        if not self.queue.resolve(job, image_id):
            raise ValueError('Задание уже передано другому загрузчику')
        self._tiles(image_id)

    def _tiles(self, image_id):
        directory = Path('map') / image_id
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / '.download-in-progress'
        marker.touch()
        self.monitor.download(image_id, 'yandex')
        TileGeometry.verify(image_id, 0)
        marker.unlink()

    def _message(self, error):
        if isinstance(error, subprocess.CalledProcessError):
            self.monitor._report_failure(error)
            return 'Ошибка скачивания или склейки; подробности в логе загрузчика.'
        if isinstance(error, requests.HTTPError):
            return f'API метаданных: HTTP {error.response.status_code}'
        if isinstance(error, requests.RequestException):
            return 'Не удалось получить метаданные: проверьте сеть и прокси.'
        return str(error) if isinstance(error, ValueError) else 'Не удалось обработать задание (' + type(error).__name__ + ').'
