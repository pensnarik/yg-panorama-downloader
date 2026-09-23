import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'monitoring-server'))
from panorama_metadata import normalize_capture

spec = importlib.util.spec_from_file_location('monitoring_server', ROOT / 'monitoring-server/monitoring-server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def capture():
    raw = json.loads((ROOT / 'tests/fixtures/yandex-panorama.json').read_text())
    return dict(schemaVersion=1, provider='yandex', imageId='Z7lngTdIrFox',
                panoramaId=raw['data']['Data']['panoramaId'],
                capturedAt='2026-09-23T18:00:00Z',
                sourceUrl='https://api-maps.yandex.ru/services/panoramas/1.x/?l=stv',
                rawResponse=raw)


class MetadataTests(unittest.TestCase):
    def test_real_response_preserves_geometry_annotations_and_unknown_fields(self):
        payload = capture()
        payload['rawResponse']['futureField'] = {'unknown': [1, 2, 3]}
        original = copy.deepcopy(payload)
        meta = normalize_capture(payload)
        self.assertEqual(payload, original)
        self.assertEqual(meta['rawResponse'], payload['rawResponse'])
        self.assertEqual(meta['projection']['Origin'], [-91.27, 20.908])
        self.assertEqual(meta['images']['Zooms'][0]['height'], 7271)
        self.assertEqual(meta['images']['Tiles'], {'width': 256, 'height': 256})
        self.assertTrue(meta['geometryFieldsPresent'])
        self.assertIn('Graph', meta['rawResponse']['data']['Annotation'])

    def test_wrong_identity_is_rejected(self):
        payload = capture()
        payload['imageId'] = 'another-panorama'
        with self.assertRaises(ValueError):
            normalize_capture(payload)

    def test_missing_geometry_is_archived_without_inventing_defaults(self):
        payload = capture()
        del payload['rawResponse']['data']['Data']['EquirectangularProjection']
        meta = normalize_capture(payload)
        self.assertFalse(meta['geometryFieldsPresent'])
        self.assertIsNone(meta['projection'])
        self.assertIn('EquirectangularProjection.Origin', meta['missingFields'])

    def test_invalid_envelopes(self):
        for payload in (None, [], {}, {'schemaVersion': 2}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                normalize_capture(payload)
        payload = capture()
        payload['capturedAt'] = '2026-09-23T18:00:00'
        with self.assertRaises(ValueError):
            normalize_capture(payload)

    def test_endpoint_transaction_and_idempotent_retry(self):
        client = server.app.test_client()
        cursor = MagicMock()
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(server.psycopg, 'connect') as connect:
            connect.return_value.__enter__.return_value = conn
            cursor.fetchone.side_effect = [('Z7lngTdIrFox',), (123,)]
            result = client.post('/aa/yandex-panorama-metadata', json=capture())
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['imageId'], 'Z7lngTdIrFox')
            calls = cursor.execute.call_args_list
            self.assertEqual(len(calls), 3)
            self.assertIn('on conflict (image_id)', calls[0].args[0])
            self.assertEqual(calls[0].args[1][3].obj['rawResponse'], capture()['rawResponse'])
            self.assertEqual(calls[1].args[1][0], 'Z7lngTdIrFox')
            self.assertEqual(calls[1].args[1][3], 1757937600)
            cursor.reset_mock()
            cursor.fetchone.side_effect = [None]
            self.assertEqual(client.post('/aa/yandex-panorama-metadata', json=capture()).status_code, 200)
            self.assertEqual(cursor.execute.call_count, 1)

    def test_bad_payload_never_reaches_database(self):
        with patch.object(server.psycopg, 'connect') as connect:
            response = server.app.test_client().post('/aa/yandex-panorama-metadata', json={})
            self.assertEqual(response.status_code, 400)
            connect.assert_not_called()

    def test_export_and_missing_record(self):
        cursor = MagicMock()
        with patch.object(server.psycopg, 'connect') as connect:
            connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cursor
            cursor.fetchone.side_effect = [(normalize_capture(capture()),), None]
            client = server.app.test_client()
            result = client.get('/aa/yandex-panorama-metadata/Z7lngTdIrFox')
            self.assertEqual(result.json['rawResponse'], capture()['rawResponse'])
            self.assertEqual(client.get('/aa/yandex-panorama-metadata/missing').status_code, 404)


if __name__ == '__main__':
    unittest.main()
