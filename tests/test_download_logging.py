#!/usr/bin/env python3
"""Concurrent log prefixes identify workers without disclosing credentials."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import TestCase
from unittest.mock import Mock, patch
from panorama_archive.logging import DownloadLog
from panorama_archive.http import RateLimitedHttp


class DownloadLoggingTests(TestCase):
    def test_parallel_contexts_do_not_mix_or_expose_credentials(self):
        self.barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(self.worker, (1, 2)))
        self.assertEqual(results, ['[поток 1 | прокси 192.0.2.1] тайл', '[поток 2 | прокси 192.0.2.2] тайл'])
        self.assertEqual(DownloadLog.format('ожидание'), '[поток 0 | прокси —] ожидание')

    def worker(self, number):
        DownloadLog.identify(number, f'socks5h://user:secret@192.0.2.{number}:1080')
        self.barrier.wait(timeout=3)
        return DownloadLog.format('тайл')

    def test_retry_message_has_worker_prefix(self):
        with ThreadPoolExecutor(max_workers=1) as executor, patch('builtins.print') as output:
            executor.submit(self.retry).result()
        self.assertTrue(output.call_args.args[0].startswith('[поток 3 | прокси 192.0.2.3] HTTP 429:'))
        self.assertNotIn('secret', output.call_args.args[0])
        self.assertTrue(output.call_args.kwargs['flush'])

    def retry(self):
        DownloadLog.identify(3, 'socks5h://user:secret@192.0.2.3:1080')
        client = RateLimitedHttp()
        client._rate_limited(Mock(headers={}), 30, 'https://example.org/tile')
