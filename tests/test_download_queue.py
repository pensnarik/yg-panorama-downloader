#!/usr/bin/env python3
"""Queue submission, execution failures and metadata resolution without network."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import requests
from panorama_archive.queue import DownloadQueue
from panorama_archive.queue_worker import QueueWorker
from panorama_archive.remote_metadata import RemoteMetadata
from panorama_archive.monitor import DownloadMonitor
from panorama_viewer.queue_ui import QueueController
from panorama_viewer.navigation_ui import NavigationOverlay
from test_metadata import capture


class RemoteMetadataTests(TestCase):
    def test_metadata_resolves_tile_id_geometry_and_name_without_logs(self):
        raw = capture()['rawResponse']
        metadata = RemoteMetadata._normalize(raw, raw['data']['Data']['panoramaId'], RemoteMetadata.ENDPOINT)
        self.assertEqual(metadata['imageId'], raw['data']['Data']['Images']['imageId'])
        self.assertEqual(metadata['position'], raw['data']['Data']['Point'])
        self.assertTrue(metadata['geometryFieldsPresent'])

    def test_wrong_panorama_is_rejected(self):
        with self.assertRaises(ValueError):
            RemoteMetadata._normalize(capture()['rawResponse'], 'wrong', RemoteMetadata.ENDPOINT)

    def test_missing_geometry_is_rejected(self):
        raw = capture()['rawResponse']
        del raw['data']['Data']['EquirectangularProjection']
        with self.assertRaises(ValueError):
            RemoteMetadata._normalize(raw, raw['data']['Data']['panoramaId'], RemoteMetadata.ENDPOINT)

    def test_fetch_uses_origin_and_closes_http_on_failure(self):
        with patch('panorama_archive.remote_metadata.ProxyList.read', return_value=[]):
            with patch('panorama_archive.remote_metadata.RateLimitedHttp') as constructor:
                constructor.return_value.get.side_effect = requests.Timeout()
                with self.assertRaises(requests.Timeout):
                    RemoteMetadata().fetch('sample')
        self.assertIn('origin=userAction', constructor.return_value.get.call_args.args[0])
        constructor.return_value.close.assert_called_once()


class QueueWorkerTests(TestCase):
    def setUp(self):
        self.worker = QueueWorker(Mock())
        self.worker.queue = Mock()
        self.job = {'id': 1, 'panorama_id': 'provider-id', 'claim_token': 'token'}

    def test_success_marks_completed_after_download(self):
        with patch.object(self.worker, '_download') as download:
            self.worker._process(self.job)
        download.assert_called_once_with(self.job)
        self.worker.queue.finish.assert_called_once_with(self.job)

    def test_network_failure_is_stored_without_credentials(self):
        with patch.object(self.worker, '_download', side_effect=requests.exceptions.ProxyError('user:secret@proxy')):
            self.worker._process(self.job)
        message = self.worker.queue.finish.call_args.args[1]
        self.assertIn('прокси', message)
        self.assertNotIn('secret', message)
        self.worker.monitor.download.assert_not_called()

    def test_resolved_image_id_is_used_for_tiles(self):
        with patch('panorama_archive.queue_worker.RemoteMetadata') as remote, patch.object(self.worker, '_tiles') as tiles:
            remote.save.return_value = 'image-id'
            self.worker._download(self.job)
        self.worker.queue.resolve.assert_called_once_with(self.job, 'image-id')
        tiles.assert_called_once_with('image-id')

    def test_lost_claim_does_not_start_download(self):
        self.worker.queue.resolve.return_value = None
        with patch('panorama_archive.queue_worker.RemoteMetadata'), self.assertRaises(ValueError):
            self.worker._download(self.job)
        self.worker.monitor.download.assert_not_called()

    def test_queue_takes_priority_over_catalog(self):
        with patch('panorama_archive.monitor.QueueWorker.process', return_value=True):
            with patch.object(DownloadMonitor, '_catalog') as catalog:
                DownloadMonitor().monitor()
        catalog.assert_not_called()

    def test_invalid_id_cannot_be_submitted(self):
        with patch.object(DownloadQueue, '_execute') as execute, self.assertRaises(ValueError):
            DownloadQueue().enqueue('../escape')
        execute.assert_not_called()


class QueueInterfaceTests(TestCase):
    def test_unavailable_arrow_is_clickable_and_gray(self):
        navigation = NavigationOverlay.__new__(NavigationOverlay)
        navigation.index, navigation.overlay, navigation.buttons = {}, Mock(), []
        with patch('panorama_viewer.navigation_ui.Gtk.Button') as constructor:
            navigation._button(SimpleNamespace(identifier='missing', name='Street'))
        button = constructor.return_value
        button.set_sensitive.assert_not_called()
        self.assertIn(('panorama-unavailable',), [call.args for call in button.add_css_class.call_args_list])

    def test_database_failure_restores_button_for_retry(self):
        viewer, button = Mock(), Mock()
        viewer.library.closed = False
        controller = QueueController(viewer)
        controller.pending.add('missing')
        controller._finished(button, 'missing', 'Ошибка БД', False)
        button.set_sensitive.assert_called_once_with(True)
        self.assertNotIn('missing', controller.pending)
        button.set_label.assert_not_called()
