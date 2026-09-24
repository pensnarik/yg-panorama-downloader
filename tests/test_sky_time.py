#!/usr/bin/env python3
"""Time defaults and recalculation when the user edits the sky timestamp."""
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import Mock
from panorama_archive.dates import ShootingDate
from panorama_viewer.sky_time import SkyTime
from panorama_viewer.sky_ui import SkyController


class SkyTimeTests(TestCase):
    def test_metadata_identifier_time_is_default(self):
        selection = SkyTime()
        instant = datetime(2025, 9, 15, 2, 52, 22, tzinfo=timezone.utc)
        selection.from_metadata(ShootingDate(2025, 9, 15, candidate=instant))
        self.assertEqual(selection.timestamp, instant)
        self.assertIn('не подтверждено', selection.explanation)

    def test_date_without_time_uses_explicit_noon_assumption(self):
        selection = SkyTime()
        selection.from_metadata(ShootingDate(2025, 9, 15))
        self.assertEqual(selection.text(), '2025-09-15 12:00:00')
        self.assertIn('условное', selection.explanation)

    def test_unknown_date_falls_back_to_now(self):
        selection = SkyTime()
        selection.from_metadata(ShootingDate())
        self.assertLess(abs((selection.timestamp - datetime.now(timezone.utc)).total_seconds()), 2)
        self.assertIn('неизвестна', selection.explanation)

    def test_conflicting_identifier_is_not_default(self):
        selection = SkyTime()
        selection.from_metadata(ShootingDate(2025, 9, 15, candidate=datetime.now(timezone.utc), conflict=True))
        self.assertEqual(selection.text(), '2025-09-15 12:00:00')

    def test_invalid_calendar_date_is_rejected(self):
        with self.assertRaises(ValueError):
            SkyTime().set_text('2025-02-29 12:00:00')


class SkyTimeControllerTests(TestCase):
    def setUp(self):
        self.controller = SkyController(Mock())
        self.controller.sun = Mock(get_active=Mock(return_value=True))
        self.controller.moon = Mock(get_active=Mock(return_value=True))
        self.controller.label = self.controller.time_hint = Mock()
        self.controller.viewer.area.panorama = Mock(data={'Point': {'coordinates': [132, 43]}})

    def edit(self, text):
        self.controller._time_changed(Mock(get_text=Mock(return_value=text)))
        return self.controller.viewer.area.sky_overlay

    def test_edit_recalculates_both_bodies(self):
        first = self.edit('2025-09-15 02:52:22').snapshot
        second = self.edit('2025-09-15 08:52:22').snapshot
        self.assertNotEqual(first.sun.azimuth, second.sun.azimuth)
        self.assertNotEqual(first.moon.azimuth, second.moon.azimuth)
        self.assertEqual(second.timestamp.hour, 8)

    def test_invalid_edit_clears_overlay_until_corrected(self):
        self.edit('2025-09-15 02:52:22')
        self.assertIsNone(self.edit('2025-02-30 02:52:22'))
        self.controller.refresh()
        self.assertIsNone(self.controller.viewer.area.sky_overlay)
        self.assertIsNotNone(self.edit('2025-02-28 02:52:22'))

    def test_timer_does_not_replace_selected_time(self):
        self.edit('2025-09-15 02:52:22')
        before = self.controller.viewer.area.sky_overlay
        self.controller._tick()
        self.assertIs(self.controller.viewer.area.sky_overlay, before)
