#!/usr/bin/env python3
"""Metadata defines the full tile grid and partial downloads stay unavailable."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from panorama_archive.tile_geometry import TileGeometry
from panorama_archive.queue_worker import QueueWorker
from panorama_viewer.navigation import LocalPanoramaIndex
from panorama_viewer.model import PanoramaLibrary
from unittest.mock import Mock


class TileGeometryTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / 'map' / 'sample'
        self.directory.mkdir(parents=True)
        self.path = self.directory / 'metadata.json'
        images = {'Tiles': {'width': 256, 'height': 256}, 'Zooms': [{'level': 0, 'width': 512, 'height': 255}]}
        self.path.write_text(json.dumps({'data': {'Data': {'Images': images, 'panoramaId': 'provider-id'}}}))

    def archive_path(self, *parts):
        return self.root.joinpath(*parts)

    def test_partial_edge_tile_is_included_in_grid(self):
        with patch('panorama_archive.tile_geometry.Path', side_effect=self.archive_path):
            self.assertEqual(TileGeometry.read('sample', 0), (2, 1))

    def test_missing_tiles_prevent_completion(self):
        with patch('panorama_archive.tile_geometry.Path', side_effect=self.archive_path):
            with self.assertRaises(ValueError):
                TileGeometry.verify('sample', 0)
            self.tiles()
            TileGeometry.verify('sample', 0)

    def tiles(self):
        (self.directory / '0').mkdir()
        for column in range(2):
            (self.directory / '0' / f'tile_{column}_0.jpg').write_bytes(b'tile')

    def test_in_progress_panorama_is_hidden_until_marker_removed(self):
        self.tiles()
        marker = self.directory / '.download-in-progress'
        marker.touch()
        self.assertEqual(LocalPanoramaIndex.build([self.path]), {})
        self.assertEqual(PanoramaLibrary.discover(self.root / 'map'), [])
        marker.unlink()
        self.assertEqual(LocalPanoramaIndex.build([self.path]), {'provider-id': self.path})
        self.assertEqual(PanoramaLibrary.discover(self.root / 'map'), [self.path])

    def test_failed_download_keeps_marker(self):
        worker = QueueWorker(Mock())
        worker.monitor.download.side_effect = OSError('disk unavailable')
        with patch('panorama_archive.queue_worker.Path', side_effect=self.archive_path), self.assertRaises(OSError):
            worker._tiles('sample')
        self.assertTrue((self.directory / '.download-in-progress').exists())

    def test_successful_download_removes_marker_after_verification(self):
        worker = QueueWorker(Mock())
        self.tiles()
        with patch('panorama_archive.queue_worker.Path', side_effect=self.archive_path):
            with patch('panorama_archive.tile_geometry.Path', side_effect=self.archive_path):
                worker._tiles('sample')
        self.assertFalse((self.directory / '.download-in-progress').exists())
        worker.monitor.download.assert_called_once_with('sample', 'yandex')
