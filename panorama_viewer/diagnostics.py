#!/usr/bin/env python3
"""Optional real GTK/GPU smoke test, separate from the application lifecycle."""
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gdk


class ViewerSmokeTest:
    def __init__(self, viewer):
        self.viewer = viewer
        self.capturing = False
        self.sources = []

    def start(self):
        self.sources = [GLib.timeout_add(100, self.poll), GLib.timeout_add_seconds(90, self.timeout)]

    def poll(self):
        try:
            if self._ready():
                return self._step()
        except Exception as error:
            self.viewer.error(f'Проверка просмотра: {error}')
            return False
        return True

    def _ready(self):
        area = self.viewer.area
        return (area.panorama is not None and hasattr(area, 'layout')
                and area.loaded_pages == area.layout.columns * area.layout.rows)

    def _step(self):
        if not self.capturing:
            self._exercise_controls()
            self._capture()
        elif self.viewer.area.snapshot_path is None:
            self._finish()
            return False
        return True

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
