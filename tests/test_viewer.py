import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from panorama_viewer.model import Panorama, atlas_layout
from panorama_viewer.projection import camera_basis, pixel_coordinates, render_cpu


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / '0').mkdir()
        self.raw = {'status': 'success', 'data': {'Data': {
            'panoramaId': 'synthetic', 'Images': {'imageId': 'test', 'Tiles': {'width': 256, 'height': 256},
            'Zooms': [{'level': 0, 'width': 1024, 'height': 400}]},
            'EquirectangularProjection': {'Origin': [0, 0]},
            'View': {'Direction': [0, 0], 'Span': [90, 60]}}}}
        self.write_metadata()
        for y in range(2):
            for x in range(4):
                im = Image.new('RGB', (256, 256 if y == 0 else 144), (x*60, y*80, 40))
                im.save(self.root / '0' / f'tile_{x}_{y}.jpg', quality=100, subsampling=0)

    def tearDown(self):
        self.tmp.cleanup()

    def write_metadata(self):
        (self.root / 'metadata.json').write_text(json.dumps(self.raw))

    def test_origin_and_pixel_angles(self):
        p = Panorama(self.root)
        self.assertAlmostEqual(p.top, math.radians(70.3125))
        self.assertAlmostEqual(p.bottom, -p.top)
        x, y, valid = pixel_coordinates(p, 1, 1, 90, 0, 60)
        self.assertAlmostEqual(float(x[0, 0]), 255.5, places=3)
        self.assertAlmostEqual(float(y[0, 0]), 199.5, places=3)
        self.assertTrue(valid[0, 0])

    def test_camera_basis_is_orthonormal_at_poles_and_seam(self):
        for yaw in (-180, 0, 359.99, 360):
            for pitch in (-89.9, 0, 89.9):
                basis = np.array(camera_basis(yaw, pitch))
                np.testing.assert_allclose(basis @ basis.T, np.eye(3), atol=1e-6)

    def test_crop_last_row_without_stretching_or_padding(self):
        p = Panorama(self.root)
        image, missing = p.read_region(0, 250, 256, 150)
        self.assertFalse(missing)
        self.assertLess(image.getpixel((100, 5))[1], 3)
        self.assertGreater(image.getpixel((100, 6))[1], 77)
        self.assertGreater(image.getpixel((100, 149))[1], 77)

    def test_missing_and_corrupt_tiles_remain_visible(self):
        (self.root / '0/tile_1_0.jpg').unlink()
        (self.root / '0/tile_2_0.jpg').write_bytes(b'not a jpeg')
        p = Panorama(self.root)
        image, missing = p.read_region(0, 0, 1024, 256)
        self.assertEqual(missing, {(1, 0), (2, 0)})
        self.assertNotEqual(image.getpixel((260, 10)), image.getpixel((292, 10)))
        self.assertEqual(p.expected_tiles, 8)

    def test_cpu_wraps_horizontal_seam_and_rejects_uncovered_ground(self):
        p = Panorama(self.root)
        # Bilinear sample straddles the last and first columns at yaw=0.
        pixel = np.array(render_cpu(p, 1, 1, 0, 0, 60))[0, 0]
        self.assertTrue(88 <= pixel[0] <= 92, pixel)
        outside = np.array(render_cpu(p, 1, 1, 0, -89, 60))[0, 0]
        np.testing.assert_array_equal(outside, [17, 22, 29])

    def test_complete_lower_resolution_preferred_over_incomplete_high(self):
        self.raw['data']['Data']['Images']['Zooms'].append({'level': 1, 'width': 512, 'height': 200})
        self.write_metadata()
        (self.root / '1').mkdir()
        for x in range(2):
            Image.new('RGB', (256, 200)).save(self.root / '1' / f'tile_{x}_0.jpg')
        (self.root / '0/tile_1_0.jpg').unlink()
        self.assertEqual(Panorama(self.root).level.number, 1)
        self.assertEqual(Panorama(self.root, level=0).level.number, 0)

    def test_real_yandex_origin_snaps_to_zenith(self):
        fixture = Path(__file__).parent / 'fixtures/yandex-panorama.json'
        self.raw = json.loads(fixture.read_text())
        self.write_metadata()
        p = Panorama(self.root)
        self.assertAlmostEqual(p.top, math.pi/2)
        self.assertAlmostEqual(p.azimuth_origin, math.radians(-91.27))
        self.assertAlmostEqual(p.bottom, math.pi/2 - 2*math.pi*7271/18944)

    def test_atlas_can_exceed_gpu_width_and_respects_memory_and_layers(self):
        side, scale, w, h, cols, rows = atlas_layout(18944, 7271, 768, max_size=16384)
        self.assertEqual((scale, w, h, cols, rows), (1, 18944, 7271, 19, 8))
        side, scale, w, h, cols, rows = atlas_layout(18944, 7271, 64, max_layers=32)
        self.assertGreater(scale, 1)
        self.assertLessEqual(cols*rows, 32)
        self.assertLessEqual(cols*rows*side*side*4, 64*1024**2)

    def test_unsupported_metadata_does_not_guess_projection(self):
        del self.raw['data']['Data']['EquirectangularProjection']
        self.write_metadata()
        with self.assertRaises(KeyError):
            Panorama(self.root)


if __name__ == '__main__':
    unittest.main()
