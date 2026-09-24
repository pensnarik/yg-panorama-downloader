#!/usr/bin/env python3
"""Local metadata recovery and automatic export for completed archives."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from panorama_archive.metadata import MetadataExporter
from panorama_archive.monitor import DownloadMonitor


class ArchiveMetadataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.exporter = MetadataExporter(self.root)
        self.metadata = {'rawResponse': {'data': {'Data': {'Images': {'imageId': 'sample'}}}}, 'unknown': [1, 2]}
        self.connection = self.enterContext(patch('panorama_archive.metadata.psycopg.connect'))
        self.cursor = self.connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value

    def test_missing_manifest_is_exported_without_changing_payload(self):
        (self.root / 'sample/0').mkdir(parents=True)
        self.cursor.fetchall.return_value = [('sample', self.metadata)]
        self.assertEqual(self.exporter.sync(), 1)
        actual = json.loads((self.root / 'sample/metadata.json').read_text())
        self.assertEqual(actual, self.metadata)
        self.cursor.execute.assert_called_once_with(MetadataExporter.QUERY, [['sample']])

    def test_existing_manifest_is_not_overwritten(self):
        (self.root / 'sample').mkdir()
        destination = self.root / 'sample/metadata.json'
        destination.write_text('existing')
        self.assertEqual(self.exporter.sync(), 0)
        self.connection.assert_not_called()
        self.assertEqual(destination.read_text(), 'existing')

    def test_export_before_download_creates_archive_directory(self):
        self.cursor.fetchall.return_value = [('sample', self.metadata)]
        self.assertEqual(self.exporter.sync(['sample']), 1)
        self.assertTrue((self.root / 'sample/metadata.json').is_file())

    def test_no_database_record_does_not_invent_geometry(self):
        self.cursor.fetchall.return_value = []
        self.assertEqual(self.exporter.sync(['sample']), 0)
        self.assertFalse((self.root / 'sample/metadata.json').exists())

    def test_invalid_identifier_never_reaches_database(self):
        self.assertEqual(self.exporter.sync(['../outside', 'a/b']), 0)
        self.connection.assert_not_called()

    def test_mismatched_metadata_is_not_written(self):
        self.cursor.fetchall.return_value = [('different', self.metadata)]
        with self.assertRaises(ValueError):
            self.exporter.sync(['different'])
        self.assertFalse((self.root / 'different').exists())

    def test_failed_write_does_not_publish_partial_manifest(self):
        self.cursor.fetchall.return_value = [('sample', self.metadata)]
        with patch.object(Path, 'write_text', side_effect=OSError('full disk')), self.assertRaises(OSError):
            self.exporter.sync(['sample'])
        self.assertFalse((self.root / 'sample/metadata.json').exists())
        self.assertEqual(list((self.root / 'sample').iterdir()), [])

    def test_monitor_syncs_even_if_all_flat_panoramas_are_already_merged(self):
        records = [{'external_id': 'sample', 'provider': 'yandex'}]
        with patch.object(MetadataExporter, 'sync') as sync, patch.object(Path, 'exists', return_value=True):
            with patch.object(DownloadMonitor, '_records', return_value=records):
                with patch.object(DownloadMonitor, 'download') as download:
                    DownloadMonitor().monitor()
        sync.assert_called_once_with()
        download.assert_not_called()

    def test_monitor_exports_metadata_before_starting_tiles(self):
        with patch.object(MetadataExporter, 'sync') as sync, patch.object(DownloadMonitor, '_execute') as execute:
            execute.side_effect = self._assert_exported
            self.sync = sync
            DownloadMonitor().download('sample', 'yandex')

    def _assert_exported(self, *arguments):
        self.sync.assert_called_once_with(['sample'])


if __name__ == '__main__':
    unittest.main()


class CatalogTitleExportTests(unittest.TestCase):
    def test_existing_manifest_receives_title_without_overwriting_raw_response(self):
        from panorama_viewer.model import MetadataValues
        with tempfile.TemporaryDirectory() as directory:
            exporter = MetadataExporter(Path(directory))
            metadata = {'rawResponse': {'data': {'Data': {'Images': {'imageId': 'sample'}, 'Point': {'name': ''}}}}}
            exporter._save('sample', metadata)
            self.assertEqual(exporter._save('sample', metadata | {'catalogTitle': 'улица Лазо'}), 1)
            path = Path(directory) / 'sample/metadata.json'
            self.assertEqual(json.loads(path.read_text())['rawResponse'], metadata['rawResponse'])
            self.assertEqual(MetadataValues.read(path)['Point']['name'], 'улица Лазо')

    def test_missing_database_title_does_not_erase_existing_title(self):
        with tempfile.TemporaryDirectory() as directory:
            exporter = MetadataExporter(Path(directory))
            metadata = {'rawResponse': {'data': {'Data': {'Images': {'imageId': 'sample'}}}}, 'catalogTitle': 'улица Лазо'}
            exporter._save('sample', metadata)
            self.assertEqual(exporter._save('sample', metadata | {'catalogTitle': ''}), 0)
            self.assertEqual(json.loads((Path(directory) / 'sample/metadata.json').read_text())['catalogTitle'], 'улица Лазо')
