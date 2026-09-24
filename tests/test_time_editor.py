#!/usr/bin/env python3
"""Calendar selection and clock edits apply only intentional valid changes."""
from unittest import TestCase
from unittest.mock import Mock
from gi.repository import Gtk
from panorama_viewer.time_editor import SkyTimeEditor


class TimeEditorTests(TestCase):
    def setUp(self):
        self.editor = SkyTimeEditor.__new__(SkyTimeEditor)
        self.editor.controller = Mock()
        self.editor.controller.time.text.return_value = '2025-09-15 02:52:17'
        self.editor.updating = False
        self.editor.date = '2025-09-15'
        self.editor.time_entry = Mock(get_text=Mock(return_value='02:52:17'))

    def test_calendar_accept_preserves_time(self):
        calendar, dialog = Mock(), Mock()
        calendar.get_date.return_value.format.return_value = '2024-02-29'
        self.editor._date_response(dialog, Gtk.ResponseType.OK, calendar)
        self.editor.controller.change_time.assert_called_once_with('2024-02-29 02:52:17')
        dialog.destroy.assert_called_once()

    def test_calendar_cancel_does_not_change_time(self):
        dialog = Mock()
        self.editor._date_response(dialog, Gtk.ResponseType.CANCEL, Mock())
        self.editor.controller.change_time.assert_not_called()
        dialog.destroy.assert_called_once()

    def test_slider_supports_end_of_day_and_preserves_date(self):
        self.editor._slid(Mock(get_value=Mock(return_value=86399)))
        self.editor.controller.change_time.assert_called_once_with('2025-09-15 23:59:59')

    def test_short_time_input_accepts_hours_and_minutes(self):
        self.editor._typed(Mock(get_text=Mock(return_value='12:34')))
        self.editor.controller.change_time.assert_called_once_with('2025-09-15 12:34:00')

    def test_typing_does_not_replace_partially_entered_clock(self):
        self.editor.typing = True
        self.editor._display_clock('12:34:00')
        self.editor.time_entry.set_text.assert_not_called()

    def test_programmatic_updates_do_not_trigger_recalculation(self):
        self.editor.updating = True
        self.editor._typed(Mock())
        self.editor._slid(Mock())
        self.editor.controller.change_time.assert_not_called()
