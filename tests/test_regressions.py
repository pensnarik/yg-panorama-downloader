#!/usr/bin/env python3
"""Characterization tests written before the class-based refactor."""
import contextlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from test_metadata import capture, normalize_capture, server
import test_viewer as viewer_tests
from panorama_viewer.model import Panorama, discover, atlas_layout
from panorama_viewer.projection import render_cpu, pixel_coordinates


class LocalArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture = viewer_tests.ViewerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root

    def test_exported_envelope_matches_raw_response(self):
        expected = Panorama(self.root)
        self.fixture.raw = {'rawResponse': self.fixture.raw}
        self.fixture.write_metadata()
        actual = Panorama(self.root / 'metadata.json')
        self.assertEqual(actual.level, expected.level)
        self.assertEqual(actual.top, expected.top)

    def test_invalid_image_id_does_not_escape_archive(self):
        self.fixture.raw['data']['Data']['Images']['imageId'] = '../../elsewhere'
        self.fixture.write_metadata()
        with self.assertRaises(ValueError):
            Panorama(self.root)

    def test_unknown_level_is_reported(self):
        with self.assertRaises(ValueError):
            Panorama(self.root, level=9)

    def test_empty_level_is_reported(self):
        for tile in (self.root / '0').glob('*.jpg'):
            tile.unlink()
        with self.assertRaises(ValueError):
            Panorama(self.root)

    def test_irrelevant_files_are_not_counted_as_tiles(self):
        for name in ('tile_99_99.jpg', 'tile_bad_name.jpg'):
            (self.root / '0' / name).write_bytes(b'ignored')
        self.assertEqual(len(Panorama(self.root).available_tiles), 8)

    def test_undersized_tile_does_not_stretch_remaining_pixels(self):
        from PIL import Image
        Image.new('RGB', (10, 10), (255, 0, 0)).save(self.root / '0/tile_0_0.jpg')
        image, failures = Panorama(self.root).read_region(0, 0, 64, 64)
        self.assertEqual(failures, {(0, 0)})
        self.assertGreater(image.getpixel((2, 2))[0], 240)
        self.assertLess(image.getpixel((20, 20))[0], 50)

    def test_discovery_is_local_and_sorted(self):
        self.assertEqual(discover(self.root.parent), [self.root / 'metadata.json'])
        self.assertEqual(discover(self.root / 'absent'), [])

    def test_full_turn_preserves_view(self):
        panorama = Panorama(self.root)
        original = render_cpu(panorama, 17, 11, 75, -10, 45)
        rotated = render_cpu(panorama, 17, 11, 435, -10, 45)
        self.assertEqual(original.tobytes(), rotated.tobytes())

    def test_camera_pitch_moves_center_up_the_source(self):
        panorama = Panorama(self.root)
        _, lower, _ = pixel_coordinates(panorama, 1, 1, 45, -20, 60)
        _, upper, _ = pixel_coordinates(panorama, 1, 1, 45, 20, 60)
        self.assertLess(upper[0, 0], lower[0, 0])

    def test_atlas_rejects_impossible_memory_budget(self):
        with self.assertRaises(ValueError):
            atlas_layout(1024, 512, 0)


class CommandLineTests(unittest.TestCase):
    setUp = LocalArchiveTests.setUp

    def invoke(self, *arguments):
        script = Path(__file__).resolve().parents[1] / 'viewer.py'
        return subprocess.run([sys.executable, str(script), *map(str, arguments)],
                              capture_output=True, text=True, timeout=20)

    def test_cli_exports_a_png_without_display(self):
        target = self.root / 'view.png'
        with patch.dict('os.environ', {'DISPLAY': '', 'WAYLAND_DISPLAY': ''}):
            result = self.invoke(self.root, '--render', target, '--width', 17, '--height', 11)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')

    def test_cli_rejects_invalid_arguments(self):
        cases = [('--fov', 'nan'), ('--fov', '180'), ('--pitch', '90'),
                 ('--gpu-memory', '0'), ('--width', '0'), ('--render', 'missing.png')]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(self.invoke(*arguments).returncode, 2)

    def test_cli_reports_missing_archive_without_traceback(self):
        result = self.invoke(self.root / 'missing.json', '--render', self.root / 'unused.png')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)


class MetadataRegressionTests(unittest.TestCase):
    def test_source_validation(self):
        for source in ('http://api-maps.yandex.ru/services/panoramas/1.x', 'https://example.org/'):
            payload = capture()
            payload['sourceUrl'] = source
            with self.subTest(source=source), self.assertRaises(ValueError):
                normalize_capture(payload)

    def test_unknown_provider_is_rejected(self):
        payload = capture()
        payload['provider'] = 'other'
        with self.assertRaises(ValueError):
            normalize_capture(payload)

    def test_nonfinite_origin_is_preserved_but_flagged(self):
        payload = capture()
        payload['rawResponse']['data']['Data']['EquirectangularProjection']['Origin'] = [True, 1]
        self.assertFalse(normalize_capture(payload)['geometryFieldsPresent'])

    def test_invalid_zoom_is_flagged(self):
        payload = capture()
        payload['rawResponse']['data']['Data']['Images']['Zooms'][0]['width'] = 0
        self.assertIn('Images.Zooms', normalize_capture(payload)['missingFields'])

    def test_capture_includes_no_invented_bbox(self):
        metadata = normalize_capture(capture())
        self.assertNotIn('angularBBox', metadata)
        self.assertIn('{level}.{x}.{y}', metadata['tileUrlTemplate'])

    def test_invalid_json_does_not_connect_to_database(self):
        with patch.object(server.psycopg, 'connect') as connect:
            response = server.app.test_client().post('/aa/yandex-panorama-metadata',
                                                      data='invalid', content_type='application/json')
        self.assertEqual(response.status_code, 400)
        connect.assert_not_called()

    def test_repository_failure_does_not_acknowledge_capture(self):
        with patch.object(server.psycopg, 'connect', side_effect=RuntimeError('offline')):
            with self.assertLogs(server.app.logger, level='ERROR'):
                response = server.app.test_client().post('/aa/yandex-panorama-metadata', json=capture())
        self.assertEqual(response.status_code, 500)


if __name__ == '__main__':
    unittest.main()
