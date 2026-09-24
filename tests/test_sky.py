#!/usr/bin/env python3
"""Independent ephemeris references, angular geometry and optional UI lifecycle."""
from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import numpy as np
from panorama_viewer.astronomy import ObserverLocation, CelestialBody, SkySnapshot, SkyOverlay, Ephemeris, CelestialGeometry
from panorama_viewer.projection import SphericalProjection
from panorama_viewer.sky_shader import SkyUniforms
from panorama_viewer.sky_ui import SkyController


class EphemerisTests(unittest.TestCase):
    def test_matches_independent_jpl_horizons_above_and_below_horizon(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/sky-horizons.json').read_text())
        location = ObserverLocation(fixture['longitude'], fixture['latitude'])
        for reference in fixture['records']:
            with self.subTest(body=reference['body'], time=reference['time']):
                snapshot = Ephemeris.calculate(location, datetime.fromisoformat(reference['time']))
                self._check_reference(snapshot, reference)

    def _check_reference(self, snapshot, reference):
        body = getattr(snapshot, reference['body'])
        self.assertAlmostEqual(math.degrees(body.azimuth), reference['azimuth'], delta=.003)
        self.assertAlmostEqual(math.degrees(body.altitude), reference['altitude'], delta=.003)
        self.assertAlmostEqual(math.degrees(body.radius) * 7200, reference['diameter_arcseconds'], delta=.2)
        self.assertAlmostEqual(body.distance, reference['distance_au'], delta=1e-6)
        if reference['body'] == 'moon':
            self.assertAlmostEqual(snapshot.moon_fraction, reference['illumination'], delta=.001)

    def test_equal_instants_in_different_timezones_match(self):
        instant = datetime(2026, 9, 24, tzinfo=timezone.utc)
        location = ObserverLocation(132, 43)
        first = Ephemeris.calculate(location, instant)
        second = Ephemeris.calculate(location, instant.astimezone(timezone(timedelta(hours=10))))
        self.assertEqual(first, second)

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            Ephemeris.calculate(ObserverLocation(0, 0), datetime(2026, 1, 1))

    def test_panorama_geojson_order_is_longitude_then_latitude(self):
        panorama = Mock(data={'Point': {'coordinates': [132.199871, 43.357577, 999]}})
        self.assertEqual(ObserverLocation.from_panorama(panorama), ObserverLocation(132.199871, 43.357577))

    def test_missing_and_invalid_coordinates_do_not_default_to_greenwich(self):
        for coordinates in ([], [1], [float('nan'), 0], [0, 91], [181, 0], [None, 0]):
            with self.subTest(coordinates=coordinates), self.assertRaises((ValueError, TypeError)):
                ObserverLocation.from_panorama(Mock(data={'Point': {'coordinates': coordinates}}))

    def test_current_calculation_is_offline_and_uses_utc(self):
        with patch('socket.socket', side_effect=AssertionError('Unexpected network request')):
            before = datetime.now(timezone.utc)
            snapshot = Ephemeris.calculate(ObserverLocation(0, 0))
        self.assertGreaterEqual(snapshot.timestamp, before)
        self.assertLessEqual(snapshot.timestamp, datetime.now(timezone.utc))


class CelestialGeometryTests(unittest.TestCase):
    def setUp(self):
        self.radius = math.radians(.25)
        self.body = CelestialBody(math.radians(359.9), math.radians(-20), self.radius, 1)

    def test_body_center_is_visible_below_horizon_at_seam(self):
        rays = SphericalProjection.rays(1, 1, 359.9, -20, 60)
        normal, inside = CelestialGeometry.surface(rays, self.body)
        self.assertTrue(inside[0, 0])
        np.testing.assert_allclose(normal[0, 0], -self.body.direction, atol=1e-4)

    def test_body_behind_camera_is_not_drawn(self):
        _, inside = CelestialGeometry.surface(np.array([-self.body.direction]), self.body)
        self.assertFalse(inside[0])

    def test_disc_boundary_is_real_angular_radius(self):
        body = CelestialBody(0, 0, self.radius, 1)
        angles = np.array([.99, 1.01]) * self.radius
        rays = np.array([np.sin(angles), np.zeros(2), np.cos(angles)]).T
        _, inside = CelestialGeometry.surface(rays, body)
        np.testing.assert_array_equal(inside, [True, False])

    def test_zoom_changes_diameter_by_perspective_scale(self):
        wide = CelestialGeometry.projected_diameter(self.body, 1000, 60)
        narrow = CelestialGeometry.projected_diameter(self.body, 1000, 15)
        self.assertAlmostEqual(wide, 7.55755, places=4)
        self.assertAlmostEqual(narrow / wide, math.tan(math.pi / 6) / math.tan(math.pi / 24))

    def test_no_minimum_disc_size(self):
        self.assertLess(CelestialGeometry.projected_diameter(self.body, 50, 110), 1)

    def test_horizon_ray_height_changes_with_pitch(self):
        level = SphericalProjection.rays(1, 1, 45, 0, 60)
        above = SphericalProjection.rays(1, 1, 45, 20, 60)
        below = SphericalProjection.rays(1, 1, 45, -20, 60)
        self.assertAlmostEqual(level[0, 0, 1], 0)
        self.assertGreater(above[0, 0, 1], 0)
        self.assertLess(below[0, 0, 1], 0)

    def test_quarter_moon_lit_side_faces_sun(self):
        moon = CelestialBody(0, 0, self.radius, .00257)
        sun = CelestialBody(math.pi / 2, 0, self.radius, 1)
        sky = SkySnapshot(datetime.now(timezone.utc), sun, moon)
        angles = np.array([-.5, .5]) * self.radius
        rays = np.array([np.sin(angles), np.zeros(2), np.cos(angles)]).T
        normals, _ = CelestialGeometry.surface(rays, moon)
        illumination = normals @ sky.moon_light
        self.assertLess(illumination[0], 0)
        self.assertGreater(illumination[1], 0)

    def test_full_and_new_moon_phases(self):
        moon = CelestialBody(0, 0, self.radius, .00257)
        for azimuth, fraction in ((0, 0), (math.pi, 1)):
            sun = CelestialBody(azimuth, 0, self.radius, 1)
            snapshot = SkySnapshot(datetime.now(timezone.utc), sun, moon)
            self.assertAlmostEqual(snapshot.moon_fraction, fraction)


class SkyControllerTests(unittest.TestCase):
    def setUp(self):
        self.viewer = Mock()
        self.controller = SkyController(self.viewer)
        self.controller.sun = Mock(get_active=Mock(return_value=True))
        self.controller.moon = Mock(get_active=Mock(return_value=False))
        self.controller.label = Mock()
        self.viewer.area.panorama = Mock(data={'Point': {'coordinates': [0, 51.4779]}})

    def test_disabled_overlay_does_not_compute_ephemeris(self):
        self.controller.sun.get_active.return_value = False
        with patch.object(Ephemeris, 'calculate') as calculate:
            self.controller.refresh()
        calculate.assert_not_called()
        self.assertIsNone(self.viewer.area.sky_overlay)

    def test_changing_panorama_replaces_the_observer_location(self):
        self.controller.refresh()
        first = self.viewer.area.sky_overlay.snapshot
        self.viewer.area.panorama = Mock(data={'Point': {'coordinates': [132, 43]}})
        self.controller.refresh()
        self.assertNotEqual(first.sun.azimuth, self.viewer.area.sky_overlay.snapshot.sun.azimuth)

    def test_missing_coordinates_clears_previous_overlay(self):
        self.controller.refresh()
        self.viewer.area.panorama = Mock(data={})
        self.controller.refresh()
        self.assertIsNone(self.viewer.area.sky_overlay)
        self.assertIn('нет координат', self.controller.label.set_text.call_args.args[0])

    def test_timer_refreshes_enabled_overlay_and_is_removed_on_close(self):
        with patch('panorama_viewer.sky_ui.GLib.timeout_add_seconds', return_value=123) as timer:
            self.controller.start()
        timer.assert_called_once_with(60, self.controller._tick)
        with patch.object(self.controller, 'refresh') as refresh:
            self.assertTrue(self.controller._tick())
        refresh.assert_called_once()
        with patch('panorama_viewer.sky_ui.GLib.source_remove') as remove:
            self.controller.close()
        remove.assert_called_once_with(123)

    def test_uniforms_disable_both_discs_when_overlay_is_absent(self):
        program = Mock()
        SkyUniforms.bind(program, None)
        self.assertEqual([call.args for call in program.integer.call_args_list], [('showSun', 0), ('showMoon', 0)])
        program.vector.assert_not_called()

    def test_moon_only_keeps_solar_lighting_but_hides_sun_disc(self):
        program = Mock()
        snapshot = Ephemeris.calculate(ObserverLocation(0, 0))
        SkyUniforms.bind(program, SkyOverlay(snapshot, False, True))
        self.assertEqual([call.args for call in program.integer.call_args_list], [('showSun', 0), ('showMoon', 1)])
        self.assertIn('moonLight', [call.args[0] for call in program.vector.call_args_list])


if __name__ == '__main__':
    unittest.main()
