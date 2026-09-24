#!/usr/bin/env python3
"""Date provenance and catalog extraction must never invent shooting times."""
import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock
from test_metadata import capture, normalize_capture
from panorama_archive.dates import DateEvidence, ShootingDate
from panorama_archive.records import PanoramaRecord
from panorama_archive.catalog import PanoramaCatalog
from panorama_viewer.model import Panorama
import test_viewer


class ShootingDateTests(unittest.TestCase):
    def setUp(self):
        self.payload = capture()
        self.data = self.payload['rawResponse']['data']['Data']

    def test_api_noon_is_a_date_not_shooting_time(self):
        result = ShootingDate.from_data(self.data)
        self.assertEqual((result.year, result.month, result.day), (2025, 9, 15))
        self.assertEqual(result.precision, 'day')
        self.assertEqual(result.candidate.isoformat(), '2025-09-15T02:52:22+00:00')
        self.assertIn('предположительно', result.label())
        self.assertNotIn('12:00', result.label())

    def test_captured_at_and_received_at_never_supply_a_shooting_date(self):
        result = ShootingDate.from_data({'capturedAt': '2026-01-01T12:00:00Z', 'receivedAt': '2026-01-02T12:00:00Z'})
        self.assertEqual(result.precision, 'unknown')
        self.assertIsNone(result.candidate)

    def test_id_without_api_is_explicitly_unverified(self):
        result = ShootingDate.from_data({'panoramaId': self.data['panoramaId']})
        self.assertEqual(result.source, 'id-inferred')
        self.assertIn('не подтверждено', result.label())

    def test_api_without_id_never_claims_a_time(self):
        result = ShootingDate.from_data({'timestamp': self.data['timestamp']})
        self.assertIsNone(result.candidate)
        self.assertIn('время неизвестно', result.label())

    def test_conflicting_dates_are_preserved_and_flagged(self):
        self.data['timestamp'] += 86400 * 4
        result = ShootingDate.from_data(self.data)
        self.assertTrue(result.conflict)
        self.assertEqual(result.day, 19)
        self.assertEqual(result.candidate.day, 15)
        self.assertIn('расходятся', result.label())

    def test_midnight_timezone_difference_is_not_false_conflict(self):
        self.data['timestamp'] += 86400
        self.assertFalse(ShootingDate.from_data(self.data).conflict)

    def test_invalid_epoch_values_and_unrecognized_ids_are_not_used(self):
        for value in (True, None, -1, 1757937600000, float('nan'), 'bad'):
            with self.subTest(value=value):
                self.assertIsNone(DateEvidence.epoch(value))
        for value in ('1757904742', 'random_1757904742', '123_456_78_bad'):
            self.assertIsNone(DateEvidence.identifier_time(value))

    def test_google_page_month_has_no_fabricated_day_or_time(self):
        for value in ('июль 2025', 'July 2025', '2025-07'):
            result = ShootingDate.from_observation('google', {'year': value})
            self.assertEqual((result.year, result.month, result.day), (2025, 7, None))
            self.assertEqual(result.precision, 'month')
            self.assertIsNone(result.candidate)

    def test_year_only_label_has_year_precision(self):
        result = ShootingDate.from_observation('yandex', {'year': '2025'})
        self.assertEqual(result.precision, 'year')
        self.assertIn('2025', result.label())
        self.assertIn('время неизвестно', result.label())

    def test_viewer_derives_date_from_old_offline_manifest(self):
        fixture = test_viewer.ViewerTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.raw['data']['Data'].update(timestamp=self.data['timestamp'], panoramaId=self.data['panoramaId'])
        fixture.write_metadata()
        self.assertEqual(Panorama(fixture.root).shooting_date.candidate.hour, 2)


class CatalogRecordTests(unittest.TestCase):
    def setUp(self):
        self.metadata = normalize_capture(capture())

    def test_geometry_coordinates_and_dates_have_separate_columns(self):
        record = PanoramaRecord(self.metadata).fields()
        self.assertAlmostEqual(record['latitude'], 43.357577)
        self.assertAlmostEqual(record['longitude'], 132.199871)
        self.assertEqual(record['origin_azimuth'], -91.27)
        self.assertEqual(record['tile_width'], 256)
        self.assertEqual(record['time_source'], 'panorama-id-unverified')
        self.assertNotEqual(record['client_observed_at'], record['time_candidate'])

    def test_unknown_fields_and_annotations_remain_lossless(self):
        self.metadata['rawResponse']['futureField'] = {'new': [1, 2, 3]}
        before = copy.deepcopy(self.metadata)
        record = PanoramaRecord(self.metadata).fields()
        self.assertEqual(record['capture_envelope'], before)
        self.assertEqual(record['raw_response']['futureField'], {'new': [1, 2, 3]})
        self.assertIn('Graph', record['annotation'])
        self.assertEqual(self.metadata, before)

    def test_client_clock_cannot_become_server_receipt_time(self):
        self.metadata['capturedAt'] = '2099-01-01T00:00:00Z'
        record = PanoramaRecord(self.metadata).fields()
        self.assertEqual(datetime.fromisoformat(record['client_observed_at']).year, 2099)
        self.assertEqual(datetime.fromisoformat(record['received_at']).year, datetime.now(timezone.utc).year)
        self.assertEqual(record['shooting_year'], 2025)

    def test_catalog_writes_levels_and_preserves_each_distinct_response(self):
        cursor = Mock()
        PanoramaCatalog.metadata(cursor, self.metadata)
        queries = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any('panorama_capture' in query for query in queries))
        levels = [query for query in queries if 'insert into aa.panorama_level' in query]
        self.assertEqual(len(levels), len(self.metadata['images']['Zooms']))


if __name__ == '__main__':
    unittest.main()
