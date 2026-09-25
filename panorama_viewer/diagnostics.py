#!/usr/bin/env python3
"""Optional real GTK/GPU smoke test, separate from the application lifecycle."""
from pathlib import Path
import math
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gdk


class ViewerSmokeTest:
    def __init__(self, viewer):
        self.viewer = viewer
        self.capturing = False
        self.navigation_checked = False
        self.history_checked = False
        self.sources = []

    def start(self):
        self.sources = [GLib.timeout_add(100, self.poll), GLib.timeout_add_seconds(90, self.timeout)]

    def poll(self):
        try:
            if self._ready():
                return self._advance()
        except Exception as error:
            self.viewer.error(f'Проверка просмотра: {error}')
            return False
        return True

    def _ready(self):
        area = self.viewer.area
        return (area.panorama is not None and hasattr(area, 'layout')
                and area.loaded_pages == area.layout.columns * area.layout.rows)

    def _advance(self):
        if not self.navigation_checked:
            self.navigation_checked = True
            return self._exercise_navigation()
        if not self.history_checked:
            self.history_checked = True
            return self._exercise_history()
        return self._step()

    def _exercise_navigation(self):
        navigation = self.viewer.navigation
        navigation._load()
        available = [(link, button) for link, button in navigation.buttons if link.identifier in navigation.index]
        if available:
            link, button = available[0]
            direction = (self.viewer.area.yaw, self.viewer.area.pitch, self.viewer.area.fov)
            button.emit('clicked')
            self._check_transition(link.identifier, direction)
        return True

    def _exercise_history(self):
        history = self.viewer.history
        available = [item for item in history.buttons if item[1].get_sensitive() and item[0].identifier in history.index]
        if available:
            link, button = next((item for item in available if item[0].label == '2019'), available[0])
            direction = (self.viewer.area.yaw, self.viewer.area.pitch, self.viewer.area.fov)
            button.emit('clicked')
            self._check_transition(link.identifier, direction)
            print(f'GTK history: switched to {link.label}')
        return True

    def _check_transition(self, identifier, direction):
        area = self.viewer.area
        assert area.panorama.panorama_id == identifier, 'Click did not open the linked panorama'
        assert (area.yaw, area.pitch, area.fov) == direction, 'Transition changed camera direction'
        print(f'GTK transition: opened {area.panorama.image_id}, camera preserved')

    def _step(self):
        if not self.capturing:
            self._exercise_widgets()
            self._capture()
        elif self.viewer.area.snapshot_path is None:
            self._finish()
            return False
        return True

    def _exercise_widgets(self):
        self._check_panel_width()
        self._exercise_controls()
        self._exercise_sky_time()
        self._exercise_time_editor()
        self._exercise_timezone()
        self._exercise_sidebar()
        self._exercise_markers()

    def _check_panel_width(self):
        panel = self.viewer.metadata_panel.revealer
        width = panel.get_width()
        assert 0 < width <= 360, f'Sidebar is too wide: {width}px'
        assert self.viewer.area.get_width() > width, 'Sidebar occupies most of the window'
        print(f'GTK sidebar: {width}px, panorama: {self.viewer.area.get_width()}px')

    def _exercise_markers(self):
        viewer = self.viewer
        viewer.marker_toggle.set_active(True)
        viewer.markers._load(viewer.area.panorama)
        viewer.area.set_view(180, 12, 100)
        viewer.markers._layout()
        if viewer.area.panorama.markers:
            self._check_visible_marker()
        viewer.marker_toggle.set_active(False)
        viewer.markers._layout()

    def _check_visible_marker(self):
        viewer = self.viewer
        direction = viewer.area.panorama.markers[0].direction
        viewer.area.set_view(math.degrees(math.atan2(direction[0], direction[2])), math.degrees(math.asin(direction[1])))
        viewer.markers._layout()
        assert viewer.markers.visible, 'Marker aimed at camera center is not visible'
        self._check_marker_label_width()
        print(f'GTK markers: {len(viewer.markers.labels)} loaded, {len(viewer.markers.visible)} visible')

    def _check_marker_label_width(self):
        from gi.repository import Gtk
        overlay = self.viewer.markers
        for marker, label in overlay.labels:
            if label.get_visible():
                minimum, natural = label.measure(Gtk.Orientation.HORIZONTAL, -1)[:2]
                assert minimum >= natural, f'Marker shrinks to an ellipsis: {marker.name}'
                assert label.get_size_request()[0] == overlay.sizes[label][0]

    def _exercise_time_editor(self):
        sky = self.viewer.sky
        assert sky.sun.get_parent() is sky.moon.get_parent(), 'Sky toggles must share a row'
        sky.editor.slider.set_value(13 * 3600 + 15 * 60)
        assert sky.editor.time_entry.get_text() == '13:15:00', 'Slider did not update time'
        assert sky.viewer.area.sky_overlay.snapshot.timestamp.hour == 13
        sky.editor.time_entry.set_text('05:30')
        assert sky.editor.slider.get_value() == 5 * 3600 + 30 * 60
        assert 'высота' in sky.label.get_tooltip_text(), 'Missing ephemeris tooltip'
        sky.select_panorama()

    def _exercise_timezone(self):
        sky = self.viewer.sky
        before = sky.time.timestamp
        sky.editor.zone_selector.set_selected(sky.editor.offsets.index(600))
        assert sky.time.timestamp == before, 'Timezone changed the calculation instant'
        assert sky.editor.time_entry.get_text() == sky.time.text().split()[1]
        sky.editor.zone_selector.set_selected(sky.editor.offsets.index(0))

    def _exercise_controls(self):
        controls, area = self.viewer.controls, self.viewer.area
        old_yaw = area.yaw
        controls.drag_begin(None, 0, 0)
        controls.drag_update(None, 50, -20)
        assert area.yaw != old_yaw, 'Drag did not rotate the camera'
        old_fov = area.fov
        controls.scroll(None, 0, -1)
        assert area.fov < old_fov, 'Scroll did not zoom'
        assert controls.key(None, Gdk.KEY_Home, 0, Gdk.ModifierType(0))

    def _exercise_sky_time(self):
        sky = self.viewer.sky
        sky.sun.set_active(True)
        sky.moon.set_active(True)
        sky.change_time('2025-09-15 02:52:22')
        before = self.viewer.area.sky_overlay.snapshot
        sky.editor.time_entry.set_text('08:52:22')
        after = self.viewer.area.sky_overlay.snapshot
        assert before.sun.azimuth != after.sun.azimuth and before.moon.azimuth != after.moon.azimuth
        sky.select_panorama()

    def _exercise_sidebar(self):
        panel = self.viewer.metadata_panel
        assert panel.revealer.get_reveal_child(), 'Sidebar should be visible initially'
        assert not self.viewer.shooting_label.get_selectable(), 'Metadata should not be selectable'
        text = self.viewer.shooting_label.get_text()
        panel.button.set_active(False)
        assert not panel.revealer.get_reveal_child(), 'Sidebar did not hide'
        panel.button.set_active(True)
        assert panel.revealer.get_reveal_child(), 'Sidebar did not reopen'
        assert self.viewer.shooting_label.get_text() == text, 'Metadata was lost'

    def _capture(self):
        options, area = self.viewer.args, self.viewer.area
        area.set_view(60.583633 if options.yaw is None else options.yaw,
                      -7.411967 if options.pitch is None else options.pitch,
                      60 if options.fov is None else options.fov)
        self.viewer.save_snapshot(str(Path(options.smoke_test).resolve()))
        self.capturing = True

    def _finish(self):
        area = self.viewer.area
        layout = area.layout
        print(f'GTK/OpenGL OK: {layout.width}x{layout.height}, '
              f'{layout.columns*layout.rows} pages, {len(area.failed_tiles)} missing tiles')
        area.cancel_loading()
        self.viewer.quit()

    def timeout(self):
        self.viewer.error('GTK smoke test timed out')
        return False
