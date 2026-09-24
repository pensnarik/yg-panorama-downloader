#!/usr/bin/env python3
"""Download messages with a thread-local, credential-free proxy identity."""
from threading import local
from urllib.parse import urlsplit


class DownloadLog:
    context = local()

    @classmethod
    def identify(cls, number, proxy):
        cls.context.number = number
        cls.context.host = urlsplit(proxy).hostname or '—'

    @classmethod
    def format(cls, message):
        number = getattr(cls.context, 'number', 0)
        host = getattr(cls.context, 'host', '—')
        return f'[поток {number} | прокси {host}] {message}'

    @classmethod
    def write(cls, message, flush=True):
        print(cls.format(message), flush=flush)
