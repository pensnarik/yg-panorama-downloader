#!/usr/bin/env python3
"""Downloader characterization with isolated files and mocked HTTP."""
import contextlib
import io
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


class DownloadCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.project = Path(__file__).resolve().parents[1]

    def execute(self, script, statuses):
        responses = [Mock(status_code=status, content=b'jpeg') for status in statuses]
        with contextlib.chdir(self.root), contextlib.redirect_stdout(io.StringIO()):
            with patch('requests.get', side_effect=responses) as get:
                with patch.object(sys, 'argv', [script, 'sample', '0' if script == 'pano.py' else '5']):
                    self._run_script(script)
        return get

    def _run_script(self, script):
        try:
            runpy.run_path(str(self.project / script), run_name='__main__')
        except SystemExit as error:
            self.assertIn(error.code, (None, 0))

    def test_yandex_boundaries_and_output(self):
        get = self.execute('pano.py', [200, 404, 404])
        self.assertEqual((self.root / 'map/sample/0/tile_0_0.jpg').read_bytes(), b'jpeg')
        self.assertEqual(get.call_count, 3)
        self.assertTrue(get.call_args_list[-1].args[0].endswith('/0.1.0'))

    def test_google_boundaries_and_output(self):
        get = self.execute('pano-google.py', [200, 400, 400])
        self.assertEqual((self.root / 'map/sample/5/tile_0_0.jpg').read_bytes(), b'jpeg')
        self.assertEqual(get.call_count, 3)
        self.assertIn('x=1&y=0&zoom=5', get.call_args_list[-1].args[0])

    def test_existing_tiles_are_not_downloaded_again(self):
        directory = self.root / 'map/sample/0'
        directory.mkdir(parents=True)
        (directory / 'tile_0_0.jpg').write_bytes(b'existing')
        get = self.execute('pano.py', [404, 404])
        self.assertEqual(get.call_count, 2)
        self.assertEqual((directory / 'tile_0_0.jpg').read_bytes(), b'existing')


class DownloadProgressTests(unittest.TestCase):
    def test_progress_reports_download_cache_boundary_and_completion(self):
        from panorama_archive.download import TileDownloader, TileProvider
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as output:
            downloader = TileDownloader(TileProvider('yandex', 'sample', 0), Path(directory))
            downloader.directory.mkdir(parents=True)
            (downloader.directory / 'tile_0_0.jpg').write_bytes(b'cached')
            downloader.http.get = Mock(side_effect=[Mock(status_code=200, content=b'new'), Mock(status_code=404), Mock(status_code=404)])
            downloader.run()
        self.check_output(output.getvalue())
        self.assertEqual(downloader.http.get.call_count, 3)

    def check_output(self, output):
        for expected in ('столбец 1/74', 'уже на диске', 'сохранён', 'граница HTTP 404',
                         'скачивание завершено; скачано 1, уже на диске 1'):
            self.assertIn(expected, output)


if __name__ == '__main__':
    unittest.main()
