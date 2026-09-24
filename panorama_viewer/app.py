#!/usr/bin/env python3
"""Application lifecycle and local library selection."""
from pathlib import Path
from threading import Thread
from .library_sync import LibraryDatabaseSync
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib
from .model import Panorama, PanoramaLibrary, MetadataValues
from .ui import WindowBuilder, FileDialog, ViewerControls
from .diagnostics import ViewerSmokeTest
from .globe_ui import GlobeExportController
from .sky_ui import SkyController


class LibrarySelection:
    def __init__(self, viewer):
        self.viewer = viewer
        self.paths = []
        self.updating = False
        self.closed = False

    def initialize(self):
        source = self.viewer.args.source
        path = Panorama.metadata_path(source) if source else None
        self.paths = PanoramaLibrary.discover(Path(self.viewer.args.library).expanduser().resolve())
        if path and path not in self.paths:
            self.paths.insert(0, path)
        self._fill_selector(self.paths.index(path) if path else 0)
        if self.paths:
            self.viewer.open_path(path or self.paths[0])

    def refresh_database(self):
        Thread(target=self._database_worker, daemon=True, name='panorama-library-sync').start()

    def _database_worker(self):
        LibraryDatabaseSync(Path(self.viewer.args.library).expanduser().resolve()).refresh()
        GLib.idle_add(self._database_loaded)

    def _database_loaded(self):
        if self.closed:
            return False
        current = self.viewer.area.panorama
        self.paths = sorted(set(self.paths) | set(PanoramaLibrary.discover(Path(self.viewer.args.library).expanduser().resolve())))
        self._refresh_title(current)
        self._select_after_refresh(current)
        return False

    def _select_after_refresh(self, current):
        selected = self.paths.index(current.path) if current and current.path in self.paths else 0
        self._fill_selector(selected)
        if current is None and self.paths:
            self.viewer.open_path(self.paths[selected])

    def _refresh_title(self, panorama):
        if panorama is None:
            return
        try:
            panorama.title = MetadataValues.read(panorama.path).get('Point', {}).get('name') or panorama.image_id
            self.viewer.window.set_title(f'{panorama.title} · {panorama.image_id} · офлайн')
            if hasattr(self.viewer.area, 'layout'):
                self.viewer.status.set_text(self.viewer.area._progress_text())
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def _fill_selector(self, selected):
        self.updating = True
        try:
            selector = self.viewer.selector
            selector.set_model(Gtk.StringList.new([PanoramaLibrary.label(path) for path in self.paths]))
            selector.set_selected(selected)
        finally:
            self.updating = False

    def selected(self, selector):
        index = selector.get_selected()
        if self.updating or index >= len(self.paths):
            return
        current = self.viewer.area.panorama
        if current is None or current.path != self.paths[index]:
            self.viewer.open_path(self.paths[index])

    def include(self, panorama):
        if panorama.path not in self.paths:
            self.paths.append(panorama.path)
            self.viewer.selector.get_model().append(f'{panorama.title} · {panorama.image_id}')
        self.viewer.selector.set_selected(self.paths.index(panorama.path))


class Viewer(Gtk.Application):
    def __init__(self, args):
        super().__init__(application_id='local.panorama.Viewer', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.args = args
        self.smoke_error = None
        self.library = LibrarySelection(self)
        self.connect('activate', self.activate_viewer)

    def activate_viewer(self, application):
        self.globe_export = GlobeExportController(self)
        self.sky = SkyController(self)
        WindowBuilder(self).build()
        self.controls = ViewerControls(self)
        self.window.present()
        GLib.idle_add(self.initial_load)

    def initial_load(self):
        self.library.initialize()
        self.library.refresh_database()
        self.sky.start()
        if self.args.smoke_test:
            self.diagnostic = ViewerSmokeTest(self)
            self.diagnostic.start()
        return False

    def close_viewer(self, *arguments):
        self.library.closed = True
        self.area.cancel_loading()
        self.sky.close()
        return False

    def select_panorama(self, selector, specification):
        self.library.selected(selector)

    def open_path(self, path):
        try:
            panorama = Panorama(path, self.args.level)
            self.area.load(panorama)
            self._show_panorama(panorama)
        except Exception as error:
            self.error(str(error))

    def _show_panorama(self, panorama):
        self.shooting_label.set_tooltip_text(panorama.shooting_date.label())
        self.area.set_view(self.args.yaw, self.args.pitch, self.args.fov)
        self.library.include(panorama)
        self.window.set_title(f'{panorama.title} · {panorama.image_id} · офлайн')
        self.sky.select_panorama()
        self.area.grab_focus()

    def choose_file(self, *arguments):
        FileDialog.open_metadata(self)

    def choose_snapshot(self, *arguments):
        FileDialog.save_snapshot(self)

    def save_snapshot(self, path):
        self.area.snapshot_path = path
        self.area.queue_render()

    def error(self, message):
        self.status.set_text('Ошибка: ' + message)
        if self.args.smoke_test:
            self.smoke_error = message
            self.quit()

    def update_view(self, yaw, pitch, fov):
        self.view_label.set_text(f'Азимут     {yaw:.1f}°\nНаклон     {pitch:+.1f}°\nОбзор       {fov:.1f}°')

    def reset(self, *arguments):
        panorama = self.area.panorama
        if panorama:
            self.area.set_view(panorama.default_yaw, panorama.default_pitch, panorama.default_fov)

    def fullscreen(self, *arguments):
        if self.window.is_fullscreen():
            self.window.unfullscreen()
        else:
            self.window.fullscreen()
