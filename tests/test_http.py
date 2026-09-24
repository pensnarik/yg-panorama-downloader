#!/usr/bin/env python3
"""Rate limiting with a virtual clock: no network or real backoff sleeps."""
import argparse
import contextlib
from email.utils import formatdate
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import requests
from panorama_archive.download import DownloadCommand, TileDownloader, TileProvider
from panorama_archive.http import RateLimitedHttp, RequestPacer, RetryAfter


class VirtualClock:
    def __init__(self):
        self.current = 1000
        self.sleeps = []

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.current += seconds


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.clock = VirtualClock()
        self.context = contextlib.ExitStack()
        self.addCleanup(self.context.close)
        self.context.enter_context(patch('panorama_archive.http.time.monotonic', self.clock.now))
        self.context.enter_context(patch('panorama_archive.http.time.time', self.clock.now))
        self.context.enter_context(patch('panorama_archive.http.time.sleep', self.clock.sleep))
        self.get = self.context.enter_context(patch('requests.get'))
        self.context.enter_context(contextlib.redirect_stdout(io.StringIO()))

    @staticmethod
    def response(status, retry_after=None):
        return Mock(status_code=status, headers={'Retry-After': retry_after}, content=b'tile', url='https://test/tile')

    def test_pause_between_successful_requests(self):
        self.get.return_value = self.response(200)
        client = RateLimitedHttp(interval=.75)
        client.get('first')
        client.get('second')
        client.get('third')
        self.assertEqual(self.clock.sleeps, [.75, .75])
        self.get.assert_called_with('third', timeout=30)

    def test_retries_same_tile_with_exponential_backoff(self):
        responses = [self.response(429) for _ in range(3)] + [self.response(200)]
        self.get.side_effect = responses
        self.assertIs(RateLimitedHttp().get('tile'), responses[-1])
        self.assertEqual(self.clock.sleeps, [30, 60, 120])
        self.assertEqual([call.args for call in self.get.call_args_list], [('tile',)] * 4)
        for response in responses[:-1]:
            response.close.assert_called_once()

    def test_retry_after_seconds_is_not_capped_by_local_limit(self):
        self.get.side_effect = [self.response(429, '1800'), self.response(200)]
        RateLimitedHttp().get('tile')
        self.assertEqual(self.clock.sleeps, [1800])

    def test_retry_after_http_date_is_respected(self):
        deadline = formatdate(self.clock.current + 120, usegmt=True)
        self.get.side_effect = [self.response(429, deadline), self.response(200)]
        RateLimitedHttp().get('tile')
        self.assertEqual(self.clock.sleeps, [120])

    def test_short_server_delay_does_not_reset_backoff(self):
        self.get.side_effect = [self.response(429, '1'), self.response(429, '1'), self.response(200)]
        RateLimitedHttp().get('tile')
        self.assertEqual(self.clock.sleeps, [30, 60])

    def test_repeated_429_stays_in_process_and_caps_only_local_backoff(self):
        self.get.side_effect = [self.response(429) for _ in range(8)] + [self.response(200)]
        RateLimitedHttp().get('tile')
        self.assertEqual(self.clock.sleeps, [30, 60, 120, 240, 480, 600, 600, 600])

    def test_success_resets_backoff_for_next_tile(self):
        self.get.side_effect = [self.response(status) for status in (429, 429, 200, 429, 200)]
        client = RateLimitedHttp()
        client.get('first')
        client.get('second')
        self.assertEqual(self.clock.sleeps, [30, 60, .5, 30])

    def test_other_http_statuses_are_returned_without_retry(self):
        for status in (400, 404, 500):
            response = self.response(status)
            self.get.return_value = response
            self.assertIs(RateLimitedHttp().get('tile'), response)
        self.assertEqual(self.get.call_count, 3)
        self.assertFalse(self.clock.sleeps)

    def test_network_error_propagates_but_pacing_is_preserved(self):
        self.get.side_effect = [requests.Timeout('slow'), self.response(200)]
        client = RateLimitedHttp()
        with self.assertRaises(requests.Timeout):
            client.get('tile')
        client.get('tile')
        self.assertEqual(self.clock.sleeps, [.5])

    def test_user_can_interrupt_rate_limit_wait(self):
        self.get.return_value = self.response(429)
        with patch('panorama_archive.http.time.sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                RateLimitedHttp().get('tile')
        self.assertEqual(self.get.call_count, 1)

    def test_invalid_or_expired_header_uses_local_backoff(self):
        values = (None, '', 'invalid', '-5', '1.5', 'NaN', 'inf', '9' * 400, formatdate(0, usegmt=True))
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(RetryAfter.seconds(value), 0)

    def test_longer_pacing_deadline_is_not_shortened(self):
        pacer = RequestPacer()
        pacer.defer(120)
        pacer.defer(.5)
        pacer.wait()
        self.assertEqual(self.clock.sleeps, [120])

    def test_invalid_interval_is_rejected_by_command_line_type(self):
        for value in ('0', '-1', 'nan', 'inf', 'bad'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                DownloadCommand._interval(value)

    def test_cli_interval_option_is_parsed(self):
        arguments = DownloadCommand._parse('yandex', ['sample', '0', '--request-interval', '2'])
        self.assertEqual(arguments.request_interval, 2)

    def test_429_body_is_not_saved_and_existing_tile_is_not_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            downloader = self._downloader(Path(directory))
            self.get.side_effect = [self.response(429), self.response(200)]
            downloader.run()
            self.assertEqual((downloader.directory / 'tile_0_0.jpg').read_bytes(), b'existing')
            self.assertEqual((downloader.directory / 'tile_0_1.jpg').read_bytes(), b'tile')
            self.assertTrue(all(call.args[0].endswith('/0.0.1') for call in self.get.call_args_list))
            self.assertEqual(list(downloader.directory.glob('*.part')), [])

    @staticmethod
    def _downloader(root):
        provider = TileProvider('yandex', 'sample', 0)
        provider.columns, provider.rows = 1, 2
        downloader = TileDownloader(provider, root)
        downloader.directory.mkdir(parents=True)
        (downloader.directory / 'tile_0_0.jpg').write_bytes(b'existing')
        return downloader


if __name__ == '__main__':
    unittest.main()
