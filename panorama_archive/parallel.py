#!/usr/bin/env python3
"""One independent HTTP session and rate limiter per SOCKS proxy."""
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from queue import Queue, Empty
from threading import Event
from .http import RateLimitedHttp

from .logging import DownloadLog

class ProxyDownloadPool:
    def __init__(self, downloader, proxies, interval):
        self.downloader, self.proxies, self.interval = downloader, proxies, interval
        self.stopped = Event()
        self.columns = Queue()
        for column in range(downloader.provider.columns):
            self.columns.put(column)

    def run(self):
        DownloadLog.write(f'Загрузка через SOCKS: {len(self.proxies)} потоков', flush=True)
        executor = ThreadPoolExecutor(max_workers=len(self.proxies))
        try:
            futures = [executor.submit(self._worker, proxy, number) for number, proxy in enumerate(self.proxies, 1)]
            for future in futures:
                future.result()
        finally:
            self.stopped.set()
            executor.shutdown(wait=True, cancel_futures=True)

    def _worker(self, proxy, number):
        DownloadLog.identify(number, proxy)
        http = RateLimitedHttp(self.interval, proxy=proxy, stopped=self.stopped)
        try:
            self._consume(http)
        except Exception as error:
            self.stopped.set()
            raise RuntimeError(DownloadLog.format(f'Загрузка остановлена ({type(error).__name__})')) from None
        finally:
            http.close()

    def _consume(self, http):
        worker = copy(self.downloader)
        worker.http = http
        while not self.stopped.is_set():
            try:
                column = self.columns.get_nowait()
            except Empty:
                return
            worker._download_column(column)
