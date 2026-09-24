#!/usr/bin/env python3
"""Opt-in PostgreSQL checks in temporary tables; production tables are untouched."""
import os
from datetime import timezone
from pathlib import Path
import re
import unittest
import psycopg
from psycopg.rows import dict_row
from panorama_archive.catalog import PanoramaCatalog
from panorama_archive.merge import ArchiveDatabase
from test_metadata import capture, normalize_capture
from repository import Queries


class TemporaryCatalogCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, query, parameters=None):
        query = re.sub(r'aa\.(panorama(?:_level|_capture|_payload)?|yandex_panorama_metadata)\b', r'pg_temp.\1', query)
        return self.cursor.execute(query, parameters)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


@unittest.skipUnless(os.environ.get('PANORAMA_DATABASE_TESTS') == '1', 'requires local PostgreSQL')
class CatalogDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.connection = psycopg.connect(**ArchiveDatabase.SETTINGS)
        self.addCleanup(self.connection.close)
        self.cursor = TemporaryCatalogCursor(self.connection.cursor(row_factory=dict_row))
        self.migrate('V003__Panorama_catalog.sql')
        self.cursor.cursor.execute('create temporary table yandex_panorama_metadata (like aa.yandex_panorama_metadata including all)')
        self.migrate('V004__Panorama_payload.sql')
        self.metadata = normalize_capture(capture())

    def migrate(self, filename):
        migration = (Path(__file__).resolve().parents[1] / 'db/migrations' / filename).read_text()
        self.cursor.execute(re.sub(r'alter table .* owner to allarchive;', '', migration))

    def test_migration_preserves_every_json_field(self):
        self.cursor.execute('drop table aa.panorama_payload, aa.panorama_level, aa.panorama_capture, aa.panorama')
        self.migrate('V003__Panorama_catalog.sql')
        from psycopg.types.json import Jsonb
        from panorama_archive.records import PanoramaRecord
        fields = dict(PanoramaRecord(self.metadata).fields(), latest_observation={'view': 'Saved observation'})
        columns = ', '.join(fields)
        self.cursor.execute(f'insert into aa.panorama ({columns}) select {columns} from jsonb_populate_record(null::aa.panorama, %s)', [Jsonb(fields)])
        self.migrate('V004__Panorama_payload.sql')
        self.assert_payload(fields)

    def assert_payload(self, fields):
        self.cursor.execute('select * from aa.panorama_payload')
        payload = self.cursor.fetchone()
        for name in ('projection', 'images', 'default_view', 'annotation', 'raw_response', 'capture_envelope', 'latest_observation'):
            self.assertEqual(payload[name], fields[name])
        self.cursor.execute('select * from aa.panorama')
        self.assertNotIn('images', self.cursor.fetchone())

    def test_payload_is_deleted_with_panorama(self):
        PanoramaCatalog.metadata(self.cursor, self.metadata)
        self.cursor.execute('delete from aa.panorama')
        self.assertEqual(self.count('panorama_payload'), 0)

    def record(self):
        self.cursor.execute('select * from aa.panorama join aa.panorama_payload using (provider, external_id)')
        return self.cursor.fetchone()

    def count(self, table):
        self.cursor.execute(f'select count(*) as count from aa.{table}')
        return self.cursor.fetchone()['count']

    def test_typed_columns_and_levels_match_provider_response(self):
        PanoramaCatalog.metadata(self.cursor, self.metadata)
        row = self.record()
        self.assertEqual(row['time_candidate'].astimezone(timezone.utc).hour, 2)
        self.assertEqual(row['shooting_year'], 2025)
        self.assertEqual(row['origin_azimuth'], -91.27)
        self.assertIsNotNone(row['received_at'])
        self.assertEqual(self.count('panorama_level'), len(self.metadata['images']['Zooms']))

    def test_ui_observation_does_not_replace_authoritative_metadata(self):
        PanoramaCatalog.metadata(self.cursor, self.metadata)
        PanoramaCatalog.observation(self.cursor, 'yandex', {'panoramaId': 'Z7lngTdIrFox',
                                    'year': '2024', 'view': 'Wrong place', 'panoramaPoint': '1,2'})
        row = self.record()
        self.assertEqual(row['shooting_year'], 2025)
        self.assertAlmostEqual(row['latitude'], 43.357577)
        self.assertEqual(row['latest_observation']['view'], 'Wrong place')

    def test_empty_api_name_preserves_address_from_plugin(self):
        self.metadata['rawResponse']['data']['Data']['Point']['name'] = '   '
        PanoramaCatalog.observation(self.cursor, 'yandex', {'panoramaId': 'Z7lngTdIrFox', 'view': 'улица Лазо'})
        PanoramaCatalog.metadata(self.cursor, self.metadata)
        self.assertEqual(self.record()['title'], 'улица Лазо')

    def test_plugin_fills_missing_address_after_metadata_capture(self):
        self.metadata['rawResponse']['data']['Data']['Point']['name'] = ''
        PanoramaCatalog.metadata(self.cursor, self.metadata)
        PanoramaCatalog.observation(self.cursor, 'yandex', {'panoramaId': 'Z7lngTdIrFox', 'view': 'улица Лазо'})
        PanoramaCatalog.metadata(self.cursor, self.metadata)
        PanoramaCatalog.observation(self.cursor, 'yandex', {'panoramaId': 'Z7lngTdIrFox', 'view': ' unknown '})
        self.assertEqual(self.record()['title'], 'улица Лазо')

    def test_month_precision_survives_unknown_or_year_only_observation(self):
        for date in ('July 2025', '2025', 'unknown'):
            PanoramaCatalog.observation(self.cursor, 'google', {'panoramaId': 'sample', 'year': date})
        row = self.record()
        self.assertEqual(row['date_precision'], 'month')
        self.assertEqual(row['shooting_month'], 7)

    def test_identical_response_is_idempotent_despite_changed_client_clock(self):
        PanoramaCatalog.metadata(self.cursor, self.metadata)
        self.metadata['capturedAt'] = '2099-01-01T00:00:00Z'
        PanoramaCatalog.metadata(self.cursor, self.metadata)
        self.assertEqual(self.count('panorama_capture'), 1)
        self.assertEqual(self.count('panorama'), 1)

    def test_distinct_responses_remain_in_history(self):
        PanoramaCatalog.metadata(self.cursor, self.metadata)
        self.metadata['rawResponse']['data']['Data']['Point']['name'] = 'New name'
        PanoramaCatalog.metadata(self.cursor, self.metadata)
        self.assertEqual(self.count('panorama_capture'), 2)
        self.assertEqual(self.record()['title'], 'New name')

    def test_caller_transaction_rolls_back_catalog_and_capture_together(self):
        with self.assertRaises(RuntimeError):
            with self.connection.transaction():
                PanoramaCatalog.metadata(self.cursor, self.metadata)
                raise RuntimeError('later operation failed')
        self.assertEqual(self.count('panorama'), 0)
        self.assertEqual(self.count('panorama_capture'), 0)

    def test_future_client_clock_does_not_block_changed_provider_response(self):
        self._legacy_write('2099-01-01T00:00:00Z')
        self.metadata['rawResponse']['data']['Data']['Point']['name'] = 'Changed response'
        self._legacy_write('2020-01-01T00:00:00Z')
        self.cursor.execute('select metadata from aa.yandex_panorama_metadata')
        self.assertEqual(self.cursor.fetchone()['metadata']['rawResponse']['data']['Data']['Point']['name'], 'Changed response')

    def _legacy_write(self, observed):
        from psycopg.types.json import Jsonb
        self.cursor.execute(Queries.UPSERT, ['Z7lngTdIrFox', self.metadata['panoramaId'], observed, Jsonb(self.metadata)])

    def test_same_response_with_changed_client_clock_does_not_create_log(self):
        self._legacy_write('2099-01-01T00:00:00Z')
        self.assertIsNotNone(self.cursor.fetchone())
        self._legacy_write('2020-01-01T00:00:00Z')
        self.assertIsNone(self.cursor.fetchone())


if __name__ == '__main__':
    unittest.main()
