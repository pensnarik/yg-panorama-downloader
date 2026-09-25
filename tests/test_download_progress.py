#!/usr/bin/env python3
"""Persistent queue icons and progress reflect complete tiles, not transient widgets."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from panorama_viewer.download_progress import DownloadProgressReader, DownloadState
from panorama_viewer.progress_ui import QueueProgressController, QueueProgressIndicator
from panorama_viewer.navigation_ui import NavigationOverlay


class ProgressReaderTests(TestCase):
    def test_only_expected_completed_tile_files_are_counted(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            images = {'Tiles': {'width': 256, 'height': 256}, 'Zooms': [{'level': 0, 'width': 512, 'height': 255}]}
            (root / 'metadata.json').write_text(json.dumps({'data': {'Data': {'Images': images}}}))
            (root / '0').mkdir()
            for name in ('tile_0_0.jpg', 'tile_1_0.jpg.part', 'tile_99_0.jpg'):
                (root / '0' / name).touch()
            self.assertEqual(DownloadProgressReader._count(root), (1, 2))

    def test_pending_job_without_metadata_has_zero_progress(self):
        row = dict(status='pending', external_id=None, error_message=None)
        state = DownloadProgressReader('/tmp')._state(row)
        self.assertEqual(state.fraction, 0)
        self.assertEqual(state.tooltip, 'В очереди')

    def test_all_tiles_do_not_imply_processing_has_finished(self):
        state = DownloadState('downloading', 10, 10)
        self.assertEqual(state.fraction, 1)
        self.assertIn('завершение обработки', state.tooltip)

    def test_error_keeps_progress_and_explains_retry(self):
        state = DownloadState('failed', 2, 10, 'ConnectionError')
        self.assertEqual(state.fraction, .2)
        self.assertIn('повтора', state.tooltip)
        self.assertIn('ConnectionError', state.tooltip)


class ProgressControllerTests(TestCase):
    def setUp(self):
        self.navigation = Mock()
        self.navigation.viewer.library.closed = False
        with patch('panorama_viewer.progress_ui.GLib') as glib:
            self.controller = QueueProgressController(self.navigation)
        self.assertEqual(glib.timeout_add_seconds.call_args.args[0], 30)
        self.state = DownloadState('downloading', 3, 10)

    def test_database_failure_keeps_last_known_state(self):
        self.controller.states = {'target': self.state}
        self.controller._received(None, 0)
        self.assertEqual(self.controller.states['target'], self.state)

    def test_old_poll_cannot_erase_newly_submitted_job(self):
        self.controller.submitted('target')
        self.controller._received({}, 0)
        self.assertIn('target', self.controller.states)
        self.assertIsNone(self.navigation.previous)

    def test_successful_poll_restores_jobs_after_restart(self):
        self.controller._received({'target': self.state}, 0)
        self.assertEqual(self.controller.states['target'].fraction, .3)
        self.assertFalse(self.controller.busy)

    def test_closed_viewer_stops_polling(self):
        self.navigation.viewer.library.closed = True
        self.assertFalse(self.controller.refresh())

    def test_overlapping_background_poll_is_not_started(self):
        self.controller.busy = True
        with patch('panorama_viewer.progress_ui.Thread') as thread:
            self.assertTrue(self.controller.refresh())
        thread.assert_not_called()


class ProgressIconTests(TestCase):
    def test_recreated_buttons_keep_hourglass_until_locally_available(self):
        navigation = NavigationOverlay.__new__(NavigationOverlay)
        state = DownloadState('downloading', 5, 10)
        navigation.progress = SimpleNamespace(states={'target': state})
        link = SimpleNamespace(identifier='target', name='Street')
        with patch('panorama_viewer.navigation_ui.QueueProgressIndicator.apply') as apply:
            navigation._appearance(Mock(), link, False)
            navigation._appearance(Mock(), link, False)
            navigation._appearance(Mock(), link, True)
        self.assertEqual(apply.call_count, 2)

    def test_icon_places_progress_below_hourglass(self):
        with patch('panorama_viewer.progress_ui.Gtk') as gtk:
            QueueProgressIndicator.apply(Mock(), DownloadState('downloading', 5, 10))
        gtk.Label.assert_called_once_with(label='⌛')
        gtk.ProgressBar.assert_called_once_with(fraction=.5, width_request=30)
        self.assertEqual(gtk.Box.return_value.append.call_args_list[0].args, (gtk.Label.return_value,))
        self.assertEqual(gtk.Box.return_value.append.call_args_list[1].args, (gtk.ProgressBar.return_value,))
