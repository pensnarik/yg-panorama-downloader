#!/usr/bin/env python3
"""Sequential HTTP requests with pacing and server-directed rate-limit waits."""
from datetime import timezone
from email.utils import parsedate_to_datetime
import math
import time
import requests

from .logging import DownloadLog

class RetryAfter:
    @classmethod
    def seconds(cls, value):
        try:
            seconds = cls._parse(value.strip())
            return max(0, seconds) if math.isfinite(seconds) else 0
        except (AttributeError, TypeError, ValueError, OverflowError):
            return 0

    @staticmethod
    def _parse(value):
        if value.isascii() and value.isdigit():
            return float(value)
        deadline = parsedate_to_datetime(value)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return deadline.timestamp() - time.time()


class RequestPacer:
    def __init__(self):
        self.ready_at = 0

    def defer(self, seconds):
        self.ready_at = max(self.ready_at, time.monotonic() + seconds)

    def wait(self, stopped=None):
        remaining = self.ready_at - time.monotonic()
        while remaining > 0:
            if stopped is None:
                time.sleep(remaining)
            elif stopped.wait(remaining):
                raise InterruptedError('Download stopped')
            remaining = self.ready_at - time.monotonic()


class RateLimitedHttp:
    INITIAL_BACKOFF = 30
    MAX_BACKOFF = 600

    def __init__(self, interval=.5, proxy=None, stopped=None):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError('request interval must be a positive finite number')
        self.interval = interval
        self.pacer = RequestPacer()
        self.stopped = stopped
        self.session = self._session(proxy) if proxy else None

    @staticmethod
    def _session(proxy):
        session = requests.Session()
        session.trust_env = False
        session.proxies = {'http': proxy, 'https': proxy}
        return session

    def close(self):
        if self.session is not None:
            self.session.close()

    def get(self, url):
        backoff = self.INITIAL_BACKOFF
        while True:
            response = self._request(url)
            if response.status_code != 429:
                return response
            self._rate_limited(response, backoff, url)
            backoff = min(backoff * 2, self.MAX_BACKOFF)

    def _request(self, url):
        if self.stopped is not None and self.stopped.is_set():
            raise InterruptedError('Download stopped')
        self.pacer.wait(self.stopped)
        try:
            return (self.session or requests).get(url, timeout=30)
        finally:
            self.pacer.defer(self.interval)

    def _rate_limited(self, response, backoff, url):
        delay = max(backoff, RetryAfter.seconds(response.headers.get('Retry-After')))
        response.close()
        self.pacer.defer(delay)
        DownloadLog.write(f'HTTP 429: waiting at least {delay:g} seconds before retrying {url}. Ctrl+C to stop.', flush=True)
