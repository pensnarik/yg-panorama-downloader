#!/usr/bin/env python3
"""Geographic marker projection, validation and screen label collision rules."""
import math
from types import SimpleNamespace
from unittest import TestCase
import numpy as np
from panorama_viewer.markers import MarkerGeometry, MarkerPlacement, PanoramaMarker, PanoramaMarkers


class MarkerGeometryTests(TestCase):
    def test_cardinal_directions_and_relative_altitude(self):
        east, distance = MarkerGeometry.direction([0, 0, 10], [.001, 0, 17])
        self.assertGreater(east[0], .99)
        self.assertAlmostEqual(east[1] * distance, 7)
        north, _ = MarkerGeometry.direction([0, 0, 0], [0, .001, 0])
        np.testing.assert_allclose(north, [0, 0, 1], atol=1e-8)

    def test_dateline_wrap_uses_nearby_direction(self):
        direction, distance = MarkerGeometry.direction([179.999, 0], [-179.999, 0])
        self.assertGreater(direction[0], .99)
        self.assertAlmostEqual(distance, 222.64, delta=.1)

    def test_projection_matches_camera_and_rejects_behind_or_offscreen(self):
        camera = SimpleNamespace(yaw=0, pitch=0, fov=60)
        for direction, expected in (([0, 0, 1], (400, 300)), ([0, 0, -1], None), ([1, 0, .01], None)):
            marker = PanoramaMarker('1', 'House 1', np.array(direction), 10)
            self.assertEqual(MarkerGeometry.screen(marker, camera, 800, 600), expected)

    def test_camera_rotation_brings_east_marker_into_view(self):
        marker = PanoramaMarker('1', '', np.array([1, 0, 0]), 10)
        camera = SimpleNamespace(yaw=90, pitch=0, fov=60)
        np.testing.assert_allclose(MarkerGeometry.screen(marker, camera, 800, 600), (400, 300), atol=.001)

    def test_invalid_and_coincident_coordinates_are_rejected(self):
        for point in ([0, 0], [0, 91], [float('nan'), 0], []):
            with self.subTest(point=point), self.assertRaises((ValueError, IndexError)):
                MarkerGeometry.direction([0, 0], point)


class MarkerAnnotationTests(TestCase):
    def test_feature_preserves_unicode_and_full_address(self):
        feature = {'geometry': {'type': 'Point', 'coordinates': [132.001, 43, 7]},
                   'properties': {'name': '42/1', 'description': 'улица Лазо, 42/1'}}
        marker = PanoramaMarkers._parse(feature, [132, 43, 0])
        self.assertEqual(marker.name, '42/1')
        self.assertEqual(marker.description, 'улица Лазо, 42/1')

    def test_malformed_features_are_ignored(self):
        for feature in (None, {}, {'geometry': None}, {'geometry': {'type': 'LineString'}, 'properties': {'name': '1'}}):
            self.assertIsNone(PanoramaMarkers._parse(feature, [0, 0]))

    def test_collisions_and_clipped_labels_are_hidden(self):
        occupied = [(100, 100, 50, 30)]
        self.assertIsNone(MarkerPlacement.rectangle((125, 115), (40, 20), (800, 600), occupied))
        self.assertIsNone(MarkerPlacement.rectangle((0, 0), (40, 20), (800, 600), []))
        self.assertEqual(MarkerPlacement.rectangle((400, 300), (40, 20), (800, 600), occupied), (380, 290, 40, 20))


class MarkerSnapshotTests(TestCase):
    def test_visible_labels_are_drawn_in_saved_view(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from PIL import Image
        from panorama_viewer.marker_snapshot import MarkerSnapshot
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'view.png'
            Image.new('RGB', (200, 100), 'black').save(path)
            MarkerSnapshot.save(path, [((50, 30, 70, 30), PanoramaMarker('42/1', '', np.array([0, 0, 1]), 10))], 200)
            self._check_pixels(path)

    def _check_pixels(self, path):
        from PIL import Image
        with Image.open(path) as image:
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 0))
            self.assertNotEqual(image.getpixel((55, 40)), (0, 0, 0))
