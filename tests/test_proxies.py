#!/usr/bin/env python3
"""SOCKS configuration and concurrent resumable downloads without network access."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
import unittest
from unittest.mock import Mock, patch
from panorama_archive.proxies import ProxyList
from panorama_archive.http import RateLimitedHttp
from panorama_archive.download import TileDownloader, TileProvider


class ProxyListTests(unittest.TestCase):
    def test_file_supports_comments_authentication_and_deduplication(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'proxies.txt'
            path.write_text('# comment\n\nuser:secret@localhost:1080\nsocks5h://user:secret@localhost:1080\n')
            self.assertEqual(ProxyList.read(path), ['socks5h://user:secret@localhost:1080'])

    def test_invalid_proxy_does_not_leak_credentials(self):
        for address in ('http://user:secret@host:1080', 'socks5://user:secret@host:bad', 'host', 'host:0'):
            with self.subTest(address=address), self.assertRaises(ValueError) as error:
                ProxyList.parse(address, 3)
            self.assertNotIn('secret', str(error.exception))
            self.assertIn('3', str(error.exception))

    def test_explicit_missing_file_is_an_error(self):
        with TemporaryDirectory() as directory, self.assertRaises(FileNotFoundError):
            ProxyList.read(Path(directory) / 'missing')

    def test_session_uses_proxy_for_both_protocols_without_environment(self):
        client = RateLimitedHttp(proxy='socks5h://localhost:1080')
        self.addCleanup(client.close)
        self.assertFalse(client.session.trust_env)
        self.assertEqual(client.session.proxies, dict.fromkeys(('http', 'https'), 'socks5h://localhost:1080'))


class FakeProxyClients:
    def __init__(self):
        self.clients, self.urls = [], []
        self.lock = Lock()
        self.barrier = Barrier(2)

    def create(self, interval, proxy, stopped):
        client = Mock()
        client.get.side_effect = self.get
        with self.lock:
            self.clients.append(client)
        return client

    def get(self, url):
        self.barrier.wait(timeout=3)
        with self.lock:
            self.urls.append(url)
        return Mock(status_code=200, content=b'tile')


class ProxyDownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        provider = TileProvider('yandex', 'sample', 0)
        provider.columns, provider.rows = 4, 1
        self.downloader = TileDownloader(provider, Path(self.directory.name), proxies=['socks5h://a:1', 'socks5h://b:2'])

    def test_workers_download_each_tile_once_and_close_sessions(self):
        factory = FakeProxyClients()
        with patch('panorama_archive.parallel.RateLimitedHttp', side_effect=factory.create), redirect_stdout(StringIO()):
            self.downloader.run()
        self.assertEqual(len(factory.clients), 2)
        self.assertEqual(len(set(factory.urls)), 4)
        self.assertEqual(len(list(self.downloader.directory.glob('*.jpg'))), 4)
        self.assertEqual(self.downloader.progress.downloaded, 4)
        for client in factory.clients:
            client.close.assert_called_once()

    def test_proxy_failure_is_sanitized_and_does_not_fall_back_to_direct(self):
        client = Mock()
        client.get.side_effect = OSError('socks5://user:secret@host:1080')
        with patch('panorama_archive.parallel.RateLimitedHttp', return_value=client), patch('requests.get') as direct:
            with redirect_stdout(StringIO()), self.assertRaises(RuntimeError) as error:
                self.downloader.run()
        self.assertNotIn('secret', str(error.exception))
        direct.assert_not_called()

    def test_existing_tiles_are_skipped_by_proxy_workers(self):
        self.downloader.directory.mkdir(parents=True)
        target = self.downloader.directory / 'tile_0_0.jpg'
        target.write_bytes(b'cached')
        client = Mock(get=Mock(return_value=Mock(status_code=200, content=b'new')))
        with patch('panorama_archive.parallel.RateLimitedHttp', return_value=client), redirect_stdout(StringIO()):
            self.downloader.run()
        self.assertEqual(client.get.call_count, 3)
        self.assertEqual(target.read_bytes(), b'cached')
        self.assertEqual(self.downloader.progress.cached, 1)

    def test_boundary_in_one_column_does_not_cancel_other_columns(self):
        client = Mock()
        client.get.return_value = Mock(status_code=404)
        with patch('panorama_archive.parallel.RateLimitedHttp', return_value=client), redirect_stdout(StringIO()):
            self.downloader.run()
        self.assertEqual(client.get.call_count, 4)
        self.assertFalse(list(self.downloader.directory.glob('*.jpg')))


if __name__ == '__main__':
    unittest.main()
