#!/usr/bin/env python3
"""Historical links use exact provider IDs and preserve the camera when switching."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from panorama_viewer.history import PanoramaHistory
from panorama_viewer.history_ui import HistoryPanel


class HistoryTests(TestCase):
    def test_current_year_is_highlighted_and_cannot_be_reopened(self):
        panel = HistoryPanel.__new__(HistoryPanel)
        panel.index = {'current': '/archive/current/metadata.json'}
        link = SimpleNamespace(identifier='current', label='2025')
        with patch('panorama_viewer.history_ui.Gtk.Button') as constructor:
            button = panel._button(link, 'current')
        button.add_css_class.assert_called_once_with('panorama-current-year')
        button.set_sensitive.assert_called_once_with(False)
        button.set_tooltip_text.assert_called_once_with('Текущая панорама')

    def test_other_year_is_not_highlighted_and_remains_available(self):
        panel = HistoryPanel.__new__(HistoryPanel)
        panel.index = {'old': '/archive/old/metadata.json'}
        with patch('panorama_viewer.history_ui.Gtk.Button'):
            button = panel._button(SimpleNamespace(identifier='old', label='2019'), 'current')
        button.add_css_class.assert_not_called()
        button.set_sensitive.assert_called_once_with(True)

    def test_years_are_sorted_deduplicated_and_resolved_from_urls(self):
        items = [{'Connection': {'oid': 'new', 'name': '2025'}},
                 {'Connection': {'href': 'https://example.org/?oid=old', 'name': '2019'}},
                 {'Connection': {'oid': 'old', 'name': '2019'}}, None]
        with patch('panorama_viewer.history.PanoramaConnections._annotation', return_value={'HistoricalPanoramas': items}):
            links = PanoramaHistory.read(Mock())
        self.assertEqual([(link.identifier, link.label) for link in links], [('old', '2019'), ('new', '2025')])

    def test_missing_history_does_not_guess_nearby_panorama(self):
        with patch('panorama_viewer.history.PanoramaConnections._annotation', return_value={}):
            self.assertEqual(PanoramaHistory.read(Mock()), [])

    def test_click_preserves_view_and_opens_exact_local_path(self):
        panel = HistoryPanel.__new__(HistoryPanel)
        panel.index = {'old': '/archive/old/metadata.json'}
        panel.viewer = Mock(area=Mock(yaw=123, pitch=-4, fov=50))
        panel._open(None, 'old')
        panel.viewer.open_path.assert_called_once_with('/archive/old/metadata.json')
        panel.viewer.area.set_view.assert_called_once_with(123, -4, 50)

    def test_missing_local_version_is_queued_instead_of_opened(self):
        panel = HistoryPanel.__new__(HistoryPanel)
        panel.index, panel.viewer, panel.queue = {}, Mock(), Mock()
        panel._open(None, 'missing')
        panel.viewer.open_path.assert_not_called()
        panel.queue.submit.assert_called_once_with(None, 'missing')

    def test_missing_year_is_clickable_and_has_distinct_color(self):
        panel = HistoryPanel.__new__(HistoryPanel)
        panel.index = {}
        with patch('panorama_viewer.history_ui.Gtk.Button'):
            button = panel._button(SimpleNamespace(identifier='old', label='2019'), 'current')
        button.set_sensitive.assert_called_once_with(True)
        button.add_css_class.assert_called_once_with('panorama-missing-year')
        button.set_tooltip_text.assert_called_once_with('Скачать панораму за эту дату')
