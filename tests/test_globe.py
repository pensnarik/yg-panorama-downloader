#!/usr/bin/env python3
"""Physical scale, gore seams, source coverage and headless PDF export."""
import contextlib
import io
import math
from pathlib import Path
import re
import unittest
from unittest.mock import Mock, patch
import numpy as np
import test_viewer
from panorama_viewer.cli import ViewerArguments, ViewerCommand
from panorama_viewer.globe import GlobeSettings, GlobeLayout, GoreProjection, GoreRenderer
from panorama_viewer.globe_pdf import GlobePdf
from panorama_viewer.model import Panorama
from panorama_viewer.globe_ui import GlobeExportController


class GlobeGeometryTests(unittest.TestCase):
    def test_physical_dimensions_for_ten_centimetre_sphere(self):
        settings = GlobeSettings()
        self.assertAlmostEqual(settings.height, 157.07963267948966)
        self.assertAlmostEqual(settings.width * settings.gores, math.pi * 100)
        self.assertEqual(settings.pixels, (155, 1856))

    def test_parallel_circumference_is_preserved(self):
        settings = GlobeSettings()
        latitude = np.array([0, .4, 1, math.pi / 2])
        actual = 2 * settings.gores * GoreProjection.half_width(settings, latitude)
        np.testing.assert_allclose(actual, math.pi * settings.diameter * np.cos(latitude))

    def test_adjacent_gores_meet_at_same_longitude_including_wrap(self):
        settings = GlobeSettings(yaw=137)
        latitude = np.array([0, -.4, .4, -1.5, 1.5])
        edge = GoreProjection.half_width(settings, latitude)
        for index in range(settings.gores):
            right, _ = GoreProjection.coordinates(settings, index, edge, latitude)
            left, _ = GoreProjection.coordinates(settings, (index + 1) % settings.gores, -edge, latitude)
            np.testing.assert_allclose(np.exp(1j * right), np.exp(1j * left), atol=1e-12)

    def test_poles_are_finite_and_outside_paper_is_masked(self):
        settings = GlobeSettings()
        longitude, inside = GoreProjection.coordinates(settings, 0, np.array([0., 1.]), math.pi / 2)
        self.assertTrue(np.isfinite(longitude).all())
        np.testing.assert_array_equal(inside, [True, False])

    def test_layout_contains_each_gore_once_with_printable_margins(self):
        for diameter in (20, 100, 104, 110, 150):
            for count in (12, 24, 48):
                settings = GlobeSettings(diameter, count)
                layout = GlobeLayout(settings)
                self.assertEqual([i for page in range(layout.pages) for i in layout.indices(page)], list(range(count)))
                self.assertLess(layout.BOTTOM + settings.height, layout.page_size[1] - 20)
                self._check_horizontal_margins(layout, settings)

    def _check_horizontal_margins(self, layout, settings):
        for page in range(layout.pages):
            for index in layout.indices(page):
                center = layout.center(page, index)
                self.assertGreaterEqual(center - settings.width / 2, layout.MARGIN)
                self.assertLessEqual(center + settings.width / 2, layout.page_size[0] - layout.MARGIN)

    def test_invalid_settings_are_rejected(self):
        cases = ({'diameter': float('nan')}, {'diameter': 151}, {'diameter': 0}, {'gores': 11},
                 {'gores': 24.5}, {'dpi': 0}, {'dpi': 601}, {'yaw': float('inf')})
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                GlobeSettings(**values)


class GlobeExportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_viewer.ViewerTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.panorama = Panorama(self.fixture.root)
        self.settings = GlobeSettings(diameter=20, gores=12, dpi=72, yaw=90)
        self.path = self.fixture.root / 'globe.pdf'

    def test_gore_center_uses_source_origin_and_azimuth(self):
        self.panorama.azimuth_origin = math.radians(30)
        horizontal, vertical, covered = GoreProjection.source(self.panorama, math.radians(120), 0)
        self.assertAlmostEqual(horizontal, 255.5)
        self.assertAlmostEqual(vertical, 199.5)
        self.assertTrue(covered)

    def test_raster_has_white_corners_grey_uncovered_poles_and_source_center(self):
        pixels = np.asarray(GoreRenderer(self.panorama, self.settings).render(0))
        height, width = pixels.shape[:2]
        np.testing.assert_array_equal(pixels[0, 0], [255, 255, 255])
        np.testing.assert_array_equal(pixels[1, width // 2], GoreRenderer.UNKNOWN)
        self.assertTrue(28 <= pixels[height // 2, width // 2, 0] <= 32)
        self.assertTrue(38 <= pixels[height // 2, width // 2, 2] <= 42)

    def test_cache_is_released_after_each_gore(self):
        renderer = GoreRenderer(self.panorama, self.settings)
        renderer.render(0)
        self.assertFalse(renderer.sampler.cache)

    def test_pdf_is_a4_and_has_expected_page_count(self):
        exporter = GlobePdf(self.panorama, self.settings)
        self.assertEqual(exporter.save(self.path), self.path)
        data = self.path.read_bytes()
        self.assertTrue(data.startswith(b'%PDF-'))
        self.assertEqual(len(re.findall(rb'/Type\s*/Page\b', data)), exporter.layout.pages)
        dimensions = re.search(rb'/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)', data)
        np.testing.assert_allclose([float(value) for value in dimensions.groups()], np.array([297, 210]) * 72 / 25.4)

    def test_pdf_image_size_and_calibration_are_in_millimetres(self):
        exporter = GlobePdf(self.panorama, self.settings)
        exporter.canvas = Mock()
        exporter._image(50, 0)
        sizes = exporter.canvas.drawImage.call_args.kwargs
        self.assertAlmostEqual(sizes['height'], self.settings.height * 72 / 25.4)
        self.assertAlmostEqual(sizes['width'], self.settings.width * 72 / 25.4)
        exporter._ruler()
        start, _, end, _ = exporter.canvas.line.call_args_list[0].args
        self.assertAlmostEqual(end - start, 50 * 72 / 25.4)

    def test_failure_preserves_existing_destination_and_removes_temporary_files(self):
        self.path.write_bytes(b'previous export')
        with patch.object(GlobePdf, '_write', side_effect=OSError('full disk')), self.assertRaises(OSError):
            GlobePdf(self.panorama, self.settings).save(self.path)
        self.assertEqual(self.path.read_bytes(), b'previous export')
        self.assertEqual(list(self.path.parent.glob('.globe-*')), [])

    def test_headless_command_exports_without_importing_gtk(self):
        arguments = [str(self.fixture.root), '--globe', str(self.path), '--globe-diameter', '20', '--globe-dpi', '72']
        with patch.dict('sys.modules', {'gi': None}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ViewerCommand.run(arguments), 0)
        self.assertTrue(self.path.read_bytes().startswith(b'%PDF-'))

    def test_wrong_extension_is_reported_without_output(self):
        with self.assertRaisesRegex(ValueError, '.pdf'):
            GlobePdf(self.panorama, self.settings).save(self.path.with_suffix('.png'))
        self.assertFalse(self.path.with_suffix('.png').exists())

    def test_cli_rejects_conflicting_modes_and_invalid_settings(self):
        cases = (['--globe', 'test.pdf'], ['source', '--globe', 'a.pdf', '--render', 'b.png'],
                 ['source', '--globe-diameter', 'nan'], ['source', '--globe-gores', '1'])
        for arguments in cases:
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    ViewerArguments().parse(arguments)
                self.assertEqual(error.exception.code, 2)


class GlobeControllerTests(unittest.TestCase):
    def setUp(self):
        self.viewer = Mock()
        self.controller = GlobeExportController(self.viewer)
        self.panorama = Mock(level=Mock(width=1024), tile_width=256)

    def test_no_duplicate_export_while_worker_is_running(self):
        self.controller.busy = True
        with patch('panorama_viewer.globe_ui.threading.Thread') as thread:
            self.controller.start(Mock(), GlobeSettings(), 'test.pdf')
        thread.assert_not_called()

    def test_export_errors_are_delivered_to_ui_thread(self):
        with patch.object(GlobePdf, 'save', side_effect=OSError('Disk full')):
            with patch('panorama_viewer.globe_ui.GLib.idle_add') as idle:
                self.controller._export(self.panorama, GlobeSettings(), 'test.pdf')
        idle.assert_called_once_with(self.controller._finished, None, 'Disk full')

    def test_error_resets_busy_state_for_retry(self):
        self.controller.busy = True
        self.assertFalse(self.controller._finished(None, 'Disk full'))
        self.assertFalse(self.controller.busy)
        self.viewer.error.assert_called_once_with('Disk full')

    def test_success_is_delivered_to_ui_thread(self):
        with patch.object(GlobePdf, 'save', return_value=Path('/tmp/test.pdf')):
            with patch('panorama_viewer.globe_ui.GLib.idle_add') as idle:
                self.controller._export(self.panorama, GlobeSettings(), '/tmp/test.pdf')
        idle.assert_called_once_with(self.controller._finished, '/tmp/test.pdf', None)


if __name__ == '__main__':
    unittest.main()
