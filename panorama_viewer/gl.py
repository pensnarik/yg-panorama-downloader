#!/usr/bin/env python3
"""GTK adapter for the renderer and cancellable page loader."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from .camera import Camera
from .gpu import GpuRenderer
from .loading import AtlasLoader


class PanoramaArea(Gtk.GLArea):
    def __init__(self, memory_mib, on_status, on_error, on_view):
        super().__init__()
        self.memory_mib = memory_mib
        self.on_status, self.on_error, self.on_view = on_status, on_error, on_view
        self._initialize_state()
        self._configure_widget()
        self.connect('realize', self._realize)
        self.connect('unrealize', self._unrealize)
        self.connect('render', self._render)

    def _initialize_state(self):
        self.camera = Camera()
        self.panorama = self.renderer = self.loader = None
        self.upload_source = self.snapshot_path = None
        self.loaded_pages = 0
        self.failed_tiles = set()
        self.sky_overlay = None

    def _configure_widget(self):
        self.set_required_version(3, 3)
        self.set_use_es(False)
        self.set_auto_render(False)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_focusable(True)

    @property
    def yaw(self):
        return self.camera.yaw

    @property
    def pitch(self):
        return self.camera.pitch

    @property
    def fov(self):
        return self.camera.fov

    def _realize(self, area):
        self.make_current()
        try:
            if self.get_error():
                raise RuntimeError(self.get_error())
            self.renderer = GpuRenderer()
            if self.panorama:
                self.load(self.panorama)
        except Exception as error:
            self.on_error(f'OpenGL: {error}')

    def cancel_loading(self):
        if self.loader:
            self.loader.cancel()
        if self.upload_source is not None:
            GLib.source_remove(self.upload_source)
            self.upload_source = None

    def _unrealize(self, area):
        self.cancel_loading()
        self.make_current()
        if not self.get_error() and self.renderer:
            self.renderer.close()
        self.renderer = None

    def set_view(self, yaw=None, pitch=None, fov=None):
        self.camera.set_view(yaw, pitch, fov)
        self.view_changed()

    def view_changed(self):
        self.on_view(self.yaw, self.pitch, self.fov)
        self.queue_render()

    def load(self, panorama):
        self.sky_overlay = None
        self.panorama = panorama
        self.set_view(panorama.default_yaw, panorama.default_pitch, panorama.default_fov)
        if self.renderer:
            try:
                self._start_loading()
            except Exception as error:
                self.on_error(f'Не удалось загрузить текстуру: {error}. Попробуйте --gpu-memory 128.')

    def _start_loading(self):
        self.cancel_loading()
        self.make_current()
        self.layout = self.renderer.prepare(self.panorama, self.memory_mib)
        self._start_worker()
        self.on_status(f'Загрузка {self.panorama.title}…')
        self.upload_source = GLib.timeout_add(10, self._upload_next)

    def _start_worker(self):
        self.loader = AtlasLoader(self.panorama, self.layout)
        self.loaded_pages = 0
        self.failed_tiles = set()
        self.loader.start()

    def _upload_next(self):
        try:
            return self._process_message(self.loader.poll())
        except Exception as error:
            self.loader.cancel()
            self.upload_source = None
            self.on_error(f'Ошибка загрузки: {error}')
            return False

    def _process_message(self, message):
        if message is None:
            return True
        if isinstance(message, Exception):
            raise message
        self._upload_page(message)
        pending = self.loaded_pages < self.layout.columns * self.layout.rows
        if not pending:
            self.upload_source = None
        return pending

    def _upload_page(self, page):
        self.make_current()
        self.renderer.atlas.upload(page)
        self.loaded_pages += 1
        self.failed_tiles.update(page.failures)
        self.on_status(self._progress_text())
        self.queue_render()

    def _progress_text(self):
        level, layout = self.panorama.level, self.layout
        return (f'{level.width} × {level.height} · уровень {level.number}'
                f' · текстура 1:{layout.scale} · {self.loaded_pages}/{layout.columns*layout.rows}'
                f' · отсутствуют/повреждены: {len(self.failed_tiles)}')

    def _render(self, area, context):
        try:
            if self.renderer and self.renderer.render(self.panorama, self.camera, self.sky_overlay):
                self._save_snapshot()
            else:
                GpuRenderer.clear()
        except Exception as error:
            self.on_error(f'Ошибка рендеринга: {error}')
        return True

    def _save_snapshot(self):
        if self.snapshot_path:
            try:
                self.renderer.save_snapshot(self.snapshot_path)
            finally:
                self.snapshot_path = None

    # Retained for diagnostic callers of the initial viewer version.
    _cancel = cancel_loading
