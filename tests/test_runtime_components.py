#!/usr/bin/env python3
"""Pure camera, background loader, OpenGL resource and archive behavior tests."""
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image

from panorama_viewer.atlas import AtlasLayout
from panorama_viewer.camera import Camera
from panorama_viewer.loading import AtlasLoader, DecodedPage
from panorama_viewer.gpu import TextureAtlas
from panorama_viewer.app import LibrarySelection
from panorama_archive.download import TileProvider, TileDownloader
from panorama_archive.merge import FlatTileMerger, CaptionPainter, ArchiveDatabase
from panorama_archive.monitor import DownloadMonitor


class CameraTests(unittest.TestCase):
    def test_view_clamps_pitch_and_fov_and_wraps_yaw(self):
        camera = Camera()
        camera.set_view(-10, 200, 500)
        self.assertEqual((camera.yaw, camera.pitch, camera.fov), (350, 89.9, 110))
        camera.set_view(pitch=-200, fov=-1)
        self.assertEqual((camera.pitch, camera.fov), (-89.9, 15))

    def test_unspecified_components_do_not_change(self):
        camera = Camera(10, 20, 30)
        camera.set_view(yaw=40)
        self.assertEqual((camera.yaw, camera.pitch, camera.fov), (40, 20, 30))

    def test_drag_uses_initial_pose_not_accumulated_offsets(self):
        camera = Camera(180, 0, 60)
        camera.begin_drag()
        camera.drag(10, 20, 100)
        first = (camera.yaw, camera.pitch)
        camera.drag(10, 20, 100)
        self.assertEqual(first, (camera.yaw, camera.pitch))
        self.assertLess(camera.yaw, 180)
        self.assertGreater(camera.pitch, 0)

    def test_scroll_limits_zoom_even_for_large_events(self):
        camera = Camera()
        camera.scroll(-10000)
        self.assertTrue(15 <= camera.fov < 60)
        camera.scroll(10000)
        self.assertAlmostEqual(camera.fov, 60)


class AtlasLoaderTests(unittest.TestCase):
    def setUp(self):
        self.panorama = MagicMock()
        self.panorama.level.width, self.panorama.level.height = 1025, 401
        self.panorama.read_region.return_value = (Image.new('RGB', (1, 1), 'red'), {(1, 1)})
        self.layout = AtlasLayout.calculate(1025, 401, 64, max_size=256)
        self.loader = AtlasLoader(self.panorama, self.layout)
        self.decoded = threading.Event()
        self.addCleanup(self.loader.cancel)

    def test_partial_page_preserves_source_boundary(self):
        page = self.loader.decode(4, 1)
        self.assertEqual((page.width, page.height), (1, 145))
        self.panorama.read_region.assert_called_once_with(1024, 256, 1, 145)
        self.assertEqual(len(page.pixels), 1*145*3)
        self.assertEqual(page.failures, {(1, 1)})

    def test_scaled_pages_have_contiguous_source_boundaries(self):
        layout = AtlasLayout.calculate(18944, 7271, 16)
        regions = [layout.source_region(18944, 7271, column, 0) for column in range(layout.columns)]
        for first, second in zip(regions, regions[1:]):
            self.assertEqual(first[0] + first[2], second[0])
        self.assertEqual(regions[-1][0] + regions[-1][2], 18944)

    def test_cancel_releases_worker_when_queue_is_full(self):
        for _ in range(3):
            self.loader.messages.put(object())
        with patch.object(self.loader, 'decode', side_effect=self._notify_decoded):
            self.loader.start()
            self.assertTrue(self.decoded.wait(1))
            self.loader.cancel()
            self.loader.thread.join(2)
        self.assertFalse(self.loader.thread.is_alive())

    def _notify_decoded(self, column, row):
        self.decoded.set()

    def test_decode_error_reaches_consumer(self):
        with patch.object(self.loader, 'decode', side_effect=OSError('broken archive')):
            self.loader.start()
            result = self.loader.messages.get(timeout=2)
            self.loader.thread.join(2)
        self.assertIsInstance(result, OSError)
        self.assertFalse(self.loader.thread.is_alive())

    def test_cancelled_loader_does_not_decode(self):
        self.loader.cancel()
        self.loader.start()
        self.loader.thread.join(2)
        self.panorama.read_region.assert_not_called()
        self.assertIsNone(self.loader.poll())

    def test_invalid_limits_are_rejected_instead_of_looping(self):
        for arguments in ((0, 1, 64), (1, 0, 64), (1, 1, 64, 0), (1, 1, 64, 1024, 0)):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                AtlasLayout.calculate(*arguments)


class TextureAtlasTests(unittest.TestCase):
    def test_upload_marks_only_the_uploaded_page_ready(self):
        with patch('panorama_viewer.gpu.GL') as graphics:
            graphics.glGenTextures.side_effect = [11, 12]
            atlas = TextureAtlas(AtlasLayout(256, 1, 512, 512, 2, 2))
            atlas.upload(DecodedPage(0, 1, 256, 128, b'pixels', set()))
            self.assertEqual(graphics.glTexSubImage3D.call_args.args[4:8], (2, 256, 128, 1))
            self.assertEqual(graphics.glTexSubImage2D.call_args.args[2:6], (0, 1, 1, 1))

    def test_failed_allocation_releases_created_texture(self):
        with patch('panorama_viewer.gpu.GL') as graphics:
            graphics.glGenTextures.return_value = 11
            graphics.glTexImage3D.side_effect = RuntimeError('out of memory')
            with self.assertRaises(RuntimeError):
                TextureAtlas(AtlasLayout(256, 1, 512, 512, 2, 2))
            graphics.glDeleteTextures.assert_called_once_with([11])

    def test_close_is_idempotent(self):
        with patch('panorama_viewer.gpu.GL') as graphics:
            graphics.glGenTextures.side_effect = [11, 12]
            atlas = TextureAtlas(AtlasLayout(256, 1, 512, 512, 2, 2))
            atlas.close()
            atlas.close()
            self.assertEqual(graphics.glDeleteTextures.call_count, 2)


class LibrarySelectionTests(unittest.TestCase):
    def setUp(self):
        self.viewer = MagicMock()
        self.library = LibrarySelection(self.viewer)
        self.library.paths = [Path('/archive/metadata.json')]
        self.viewer.selector.get_selected.return_value = 0
        self.viewer.area.panorama = None

    def test_programmatic_changes_do_not_open_panorama(self):
        self.library.updating = True
        self.library.selected(self.viewer.selector)
        self.viewer.open_path.assert_not_called()

    def test_new_selection_opens_the_correct_archive(self):
        self.library.selected(self.viewer.selector)
        self.viewer.open_path.assert_called_once_with(self.library.paths[0])

    def test_current_selection_does_not_reload_textures(self):
        self.viewer.area.panorama = MagicMock(path=self.library.paths[0])
        self.library.selected(self.viewer.selector)
        self.viewer.open_path.assert_not_called()

    def test_failed_model_update_does_not_leave_selection_blocked(self):
        self.viewer.selector.set_model.side_effect = RuntimeError('widget unavailable')
        with self.assertRaises(RuntimeError):
            self.library._fill_selector(0)
        self.assertFalse(self.library.updating)


class ArchiveComponentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_sparse_merge_keeps_column_positions_and_marks_missing_tiles(self):
        Image.new('RGB', (8, 8), 'red').save(self.root / 'tile_0_0.jpg')
        Image.new('RGB', (8, 8), 'blue').save(self.root / 'tile_2_0.jpg')
        image = FlatTileMerger(self.root, 8).merge()
        self.assertEqual(image.size, (24, 8))
        self.assertEqual(image.getpixel((12, 4)), (0, 128, 0))
        self.assertGreater(image.getpixel((20, 4))[2], 240)

    def test_merge_rejects_empty_archive(self):
        with self.assertRaises(ValueError):
            FlatTileMerger(self.root, 256)

    def test_caption_changes_image_without_changing_dimensions(self):
        image = Image.new('RGB', (400, 150), 'black')
        CaptionPainter().paint(image, 'Archive')
        self.assertEqual(image.size, (400, 150))
        self.assertIsNotNone(image.getbbox())

    def test_title_uses_timestamp_and_optional_name(self):
        row = dict(unix_timestamp='2025-01-01', date='2025', lat=43, lon=132, view_name='Street')
        self.assertEqual(ArchiveDatabase._format_title(row), '2025-01-01, 43,132 | Street')
        row['view_name'] = None
        self.assertEqual(ArchiveDatabase._format_title(row), '2025-01-01, 43,132')

    def test_failed_download_does_not_create_a_tile(self):
        downloader = TileDownloader(TileProvider('yandex', 'sample', 0), self.root)
        response = MagicMock(status_code=500, url='https://example.org/tile')
        with patch('requests.get', return_value=response), self.assertRaises(RuntimeError):
            downloader.run()
        self.assertEqual(list(self.root.rglob('*.jpg')), [])

    def test_monitor_does_not_merge_after_downloader_failure(self):
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'download')) as execute:
            with self.assertRaises(subprocess.CalledProcessError):
                DownloadMonitor().download('sample', 'yandex')
        self.assertEqual(execute.call_count, 1)

    def test_monitor_passes_arguments_without_shell_interpolation(self):
        identifier = 'sample;echo unwanted'
        with patch('subprocess.run') as execute:
            DownloadMonitor().download(identifier, 'yandex')
        self.assertEqual(execute.call_count, 2)
        self.assertIn(identifier, execute.call_args_list[0].args[0])
        self.assertNotIn('shell', execute.call_args.kwargs)
        self.assertTrue(execute.call_args.kwargs['check'])


if __name__ == '__main__':
    unittest.main()
