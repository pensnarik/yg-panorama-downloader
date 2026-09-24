#!/usr/bin/env python3
"""Database failures preserve offline startup and local metadata."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch, Mock
import psycopg
from panorama_viewer.library_sync import LibraryDatabaseSync
from panorama_viewer.app import LibrarySelection


class LibrarySyncTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.sync = LibraryDatabaseSync(self.root)
        self.metadata = {'rawResponse': {'data': {'Data': {'Images': {'imageId': 'sample'}}}}}
        self.tiles = self.root / 'sample/0'
        self.tiles.mkdir(parents=True)
        (self.tiles / 'tile_0_0.jpg').write_bytes(b'tile')

    def test_database_adds_manifest_for_downloaded_panorama(self):
        with patch.object(self.sync, '_records', return_value=[('sample', self.metadata)]):
            self.assertEqual(self.sync.refresh(), 1)
        self.assertTrue((self.root / 'sample/metadata.json').exists())

    def test_database_failure_preserves_existing_manifest(self):
        manifest = self.root / 'sample/metadata.json'
        manifest.write_text('local')
        with patch.object(self.sync, '_records', side_effect=psycopg.OperationalError('offline')):
            self.assertEqual(self.sync.refresh(), 0)
        self.assertEqual(manifest.read_text(), 'local')

    def test_panorama_without_tiles_is_not_added(self):
        (self.tiles / 'tile_0_0.jpg').unlink()
        with patch.object(self.sync, '_records', return_value=[('sample', self.metadata)]):
            self.assertEqual(self.sync.refresh(), 0)
        self.assertFalse((self.root / 'sample/metadata.json').exists())

    def test_existing_metadata_is_not_overwritten(self):
        manifest = self.root / 'sample/metadata.json'
        manifest.write_text('local')
        with patch.object(self.sync, '_records', return_value=[('sample', self.metadata)]):
            self.assertEqual(self.sync.refresh(), 0)
        self.assertEqual(manifest.read_text(), 'local')

    def test_invalid_record_does_not_block_valid_records(self):
        with patch.object(self.sync, '_records', return_value=[('../invalid', {}), ('bad', {}), ('sample', self.metadata)]):
            self.assertEqual(self.sync.refresh(), 1)

    def test_refresh_preserves_current_panorama_and_local_only_entries(self):
        viewer = Mock(args=Mock(library=str(self.root)))
        selection = LibrarySelection(viewer)
        selection.paths = [self.root / 'local/metadata.json']
        viewer.area.panorama.path = selection.paths[0]
        with patch.object(selection, '_fill_selector') as fill:
            selection._database_loaded()
        self.assertEqual(selection.paths, [self.root / 'local/metadata.json'])
        viewer.open_path.assert_not_called()
        fill.assert_called_once_with(0)

    def test_closed_viewer_ignores_database_completion(self):
        selection = LibrarySelection(Mock())
        selection.closed = True
        with patch.object(selection, '_fill_selector') as fill:
            self.assertFalse(selection._database_loaded())
        fill.assert_not_called()
