#!/usr/bin/env python3
"""Metadata normalization and HTTP persistence contracts."""
import copy
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'monitoring-server'))
from panorama_metadata import normalize_capture


class MetadataFixtures:
    @staticmethod
    def server():
        specification = importlib.util.spec_from_file_location('monitoring_server', ROOT / 'monitoring-server/monitoring-server.py')
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module

    @staticmethod
    def capture():
        raw = json.loads((ROOT / 'tests/fixtures/yandex-panorama.json').read_text())
        return dict(schemaVersion=1, provider='yandex', imageId='Z7lngTdIrFox',
                    panoramaId=raw['data']['Data']['panoramaId'], capturedAt='2026-09-23T18:00:00Z',
                    sourceUrl='https://api-maps.yandex.ru/services/panoramas/1.x/?l=stv', rawResponse=raw)


server = MetadataFixtures.server()
capture = MetadataFixtures.capture


class MetadataTests(unittest.TestCase):
    @contextmanager
    def database(self, rows):
        cursor, connection = MagicMock(), MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.side_effect = rows
        with patch.object(server.psycopg, 'connect') as connect:
            connect.return_value.__enter__.return_value = connection
            yield cursor

    def test_real_response_preserves_unknown_fields_without_mutating_input(self):
        payload = capture()
        payload['rawResponse']['futureField'] = {'unknown': [1, 2, 3]}
        original = copy.deepcopy(payload)
        metadata = normalize_capture(payload)
        self.assertEqual(payload, original)
        self.assertEqual(metadata['rawResponse'], payload['rawResponse'])
        self.assertIn('Graph', metadata['rawResponse']['data']['Annotation'])

    def test_geometry_retains_original_units_and_dimensions(self):
        metadata = normalize_capture(capture())
        self.assertEqual(metadata['projection']['Origin'], [-91.27, 20.908])
        self.assertEqual(metadata['images']['Zooms'][0]['height'], 7271)
        self.assertEqual(metadata['images']['Tiles'], {'width': 256, 'height': 256})
        self.assertTrue(metadata['geometryFieldsPresent'])

    def test_wrong_identity_is_rejected(self):
        payload = capture()
        payload['imageId'] = 'another-panorama'
        with self.assertRaises(ValueError):
            normalize_capture(payload)

    def test_missing_geometry_is_archived_without_inventing_defaults(self):
        payload = capture()
        del payload['rawResponse']['data']['Data']['EquirectangularProjection']
        metadata = normalize_capture(payload)
        self.assertFalse(metadata['geometryFieldsPresent'])
        self.assertIsNone(metadata['projection'])
        self.assertIn('EquirectangularProjection.Origin', metadata['missingFields'])

    def test_invalid_envelopes(self):
        for payload in (None, [], {}, {'schemaVersion': 2}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                normalize_capture(payload)
        payload = capture()
        payload['capturedAt'] = '2026-09-23T18:00:00'
        with self.assertRaises(ValueError):
            normalize_capture(payload)

    def test_endpoint_persists_raw_json_and_acknowledges_image(self):
        with self.database([('Z7lngTdIrFox',), (123,)]) as cursor:
            result = server.app.test_client().post('/aa/yandex-panorama-metadata', json=capture())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['imageId'], 'Z7lngTdIrFox')
        calls = cursor.execute.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertIn('on conflict (image_id)', calls[0].args[0])
        self.assertEqual(calls[0].args[1][3].obj['rawResponse'], capture()['rawResponse'])

    def test_authoritative_coordinates_are_logged_in_lat_lon_order(self):
        with self.database([('Z7lngTdIrFox',), (123,)]) as cursor:
            server.app.test_client().post('/aa/yandex-panorama-metadata', json=capture())
        values = cursor.execute.call_args_list[1].args[1]
        self.assertEqual(values[0], 'Z7lngTdIrFox')
        self.assertAlmostEqual(values[1], 43.357577)
        self.assertAlmostEqual(values[2], 132.199871)
        self.assertEqual(values[3], 1757937600)

    def test_idempotent_retry_does_not_duplicate_log(self):
        with self.database([None]) as cursor:
            result = server.app.test_client().post('/aa/yandex-panorama-metadata', json=capture())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(cursor.execute.call_count, 1)

    def test_bad_payload_never_reaches_database(self):
        with patch.object(server.psycopg, 'connect') as connect:
            response = server.app.test_client().post('/aa/yandex-panorama-metadata', json={})
            self.assertEqual(response.status_code, 400)
            connect.assert_not_called()

    def test_export_and_missing_record(self):
        with self.database([(normalize_capture(capture()),), None]):
            client = server.app.test_client()
            result = client.get('/aa/yandex-panorama-metadata/Z7lngTdIrFox')
            self.assertEqual(result.json['rawResponse'], capture()['rawResponse'])
            self.assertEqual(client.get('/aa/yandex-panorama-metadata/missing').status_code, 404)


if __name__ == '__main__':
    unittest.main()
