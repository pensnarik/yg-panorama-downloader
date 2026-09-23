import json
import math
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Gio, GLib

from .gl import PanoramaArea
from .model import Panorama, discover


class Viewer(Gtk.Application):
    def __init__(self, args):
        super().__init__(application_id='local.panorama.Viewer', flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.args = args
        self.paths = []
        self.smoke_error = None
        self.smoke_stage = 0
        self.closed = False
        self.setting_selector = False
        self.connect('activate', self.activate_viewer)

    def activate_viewer(self, app):
        self.window = Gtk.ApplicationWindow(application=self, title='Панорамы · офлайн')
        self.window.set_default_size(1180, 800)
        self.window.connect('close-request', self.close_viewer)
        header = Gtk.HeaderBar()
        self.window.set_titlebar(header)
        open_button = Gtk.Button(label='Открыть…')
        open_button.connect('clicked', self.choose_file)
        header.pack_start(open_button)
        self.selector = Gtk.DropDown.new_from_strings([])
        self.selector.set_tooltip_text('Локальные панорамы с metadata.json')
        self.selector.connect('notify::selected', self.select_panorama)
        header.pack_start(self.selector)
        reset = Gtk.Button(label='Сбросить вид')
        reset.connect('clicked', lambda *_: self.reset())
        header.pack_end(reset)
        fullscreen = Gtk.Button(icon_name='view-fullscreen-symbolic')
        fullscreen.set_tooltip_text('Полный экран · F11')
        fullscreen.connect('clicked', lambda *_: self.fullscreen())
        header.pack_end(fullscreen)
        save = Gtk.Button(icon_name='camera-photo-symbolic')
        save.set_tooltip_text('Сохранить текущий вид · Ctrl+S')
        save.connect('clicked', self.choose_snapshot)
        header.pack_end(save)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window.set_child(box)
        self.status = Gtk.Label(label='Откройте metadata.json или выберите панораму из списка.', xalign=0)
        self.status.set_margin_start(12)
        self.status.set_margin_end(12)
        self.status.set_margin_top(6)
        self.status.set_margin_bottom(6)
        self.status.set_selectable(True)
        self.status.set_wrap(True)
        self.area = PanoramaArea(self.args.gpu_memory, self.status.set_text, self.error, self.update_view)
        box.append(self.area)
        box.append(self.status)
        self.view_label = Gtk.Label(label='Мышь — осмотреться · колесо — масштаб · стрелки · Home · F11')
        self.view_label.set_margin_bottom(8)
        box.append(self.view_label)

        drag = Gtk.GestureDrag.new()
        drag.set_button(1)
        drag.connect('drag-begin', self.drag_begin)
        drag.connect('drag-update', self.drag_update)
        self.area.add_controller(drag)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect('scroll', self.scroll)
        self.area.add_controller(scroll)
        keys = Gtk.EventControllerKey.new()
        keys.connect('key-pressed', self.key)
        self.window.add_controller(keys)
        self.window.present()
        GLib.idle_add(self.initial_load)

    def close_viewer(self, *_):
        self.closed = True
        self.area._cancel()
        return False

    def initial_load(self):
        source = Path(self.args.source).expanduser().resolve() if self.args.source else None
        root = Path(self.args.library).expanduser().resolve()
        self.paths = discover(root)
        if source:
            source = source / 'metadata.json' if source.is_dir() else source
            if source not in self.paths:
                self.paths.insert(0, source)
        labels = []
        for path in self.paths:
            try:
                raw = json.loads(path.read_text())
                data = raw.get('rawResponse', raw)['data']['Data']
                labels.append(f"{data.get('Point', {}).get('name', path.parent.name)} · {data['Images']['imageId']}")
            except (OSError, ValueError, KeyError, TypeError):
                labels.append(path.parent.name)
        self.setting_selector = True
        self.selector.set_model(Gtk.StringList.new(labels))
        if self.paths:
            index = self.paths.index(source) if source else 0
            # Explicit load also covers the unchanged initial selection (index 0).
            self.selector.set_selected(index)
            self.setting_selector = False
            self.open_path(self.paths[index])
        self.setting_selector = False
        if self.args.smoke_test:
            GLib.timeout_add(100, self.smoke_poll)
            GLib.timeout_add_seconds(90, self.smoke_timeout)
        return False

    def select_panorama(self, widget, _):
        if self.setting_selector:
            return
        index = widget.get_selected()
        if index < len(self.paths):
            path = self.paths[index]
            if not self.area.panorama or self.area.panorama.path != path:
                self.open_path(path)

    def open_path(self, path):
        try:
            panorama = Panorama(path, self.args.level)
            self.area.load(panorama)
            self.area.set_view(self.args.yaw, self.args.pitch, self.args.fov)
            if panorama.path not in self.paths:
                self.paths.append(panorama.path)
                self.selector.get_model().append(f'{panorama.title} · {panorama.image_id}')
            self.selector.set_selected(self.paths.index(panorama.path))
            self.window.set_title(f'{panorama.title} · {panorama.image_id} · офлайн')
            self.area.grab_focus()
        except Exception as error:
            self.error(str(error))

    def choose_file(self, *_):
        dialog = Gtk.FileChooserNative.new('Открыть метаданные панорамы', self.window,
                                            Gtk.FileChooserAction.OPEN, 'Открыть', 'Отмена')
        file_filter = Gtk.FileFilter()
        file_filter.set_name('Метаданные JSON')
        file_filter.add_pattern('*.json')
        dialog.add_filter(file_filter)
        def response(chooser, result):
            if result == Gtk.ResponseType.ACCEPT:
                self.open_path(chooser.get_file().get_path())
            chooser.destroy()
        dialog.connect('response', response)
        dialog.show()

    def choose_snapshot(self, *_):
        if not self.area.panorama:
            return
        dialog = Gtk.FileChooserNative.new('Сохранить текущий вид', self.window,
                                            Gtk.FileChooserAction.SAVE, 'Сохранить', 'Отмена')
        dialog.set_current_name(f'{self.area.panorama.image_id}_view.png')
        def response(chooser, result):
            if result == Gtk.ResponseType.ACCEPT:
                self.area.snapshot_path = chooser.get_file().get_path()
                self.area.queue_render()
            chooser.destroy()
        dialog.connect('response', response)
        dialog.show()

    def error(self, message):
        self.status.set_text('Ошибка: ' + message)
        if self.args.smoke_test:
            self.smoke_error = message
            self.quit()

    def update_view(self, yaw, pitch, fov):
        self.view_label.set_text(f'Азимут {yaw:.1f}° · наклон {pitch:+.1f}° · обзор {fov:.1f}°'
                                 '     Мышь · колесо · стрелки · Home · F11')

    def reset(self):
        p = self.area.panorama
        if p:
            self.area.set_view(p.default_yaw, p.default_pitch, p.default_fov)

    def fullscreen(self):
        if self.window.is_fullscreen():
            self.window.unfullscreen()
        else:
            self.window.fullscreen()

    def drag_begin(self, _, x, y):
        self.area.grab_focus()
        self.drag_origin = (self.area.yaw, self.area.pitch)

    def drag_update(self, _, dx, dy):
        scale = 2 * math.tan(math.radians(self.area.fov)/2) / max(1, self.area.get_height())
        self.area.set_view(self.drag_origin[0] - math.degrees(math.atan(dx*scale)),
                           self.drag_origin[1] + math.degrees(math.atan(dy*scale)))

    def scroll(self, _, dx, dy):
        self.area.set_view(fov=self.area.fov * math.exp(max(-2, min(2, dy)) * .09))
        return True

    def key(self, _, key, code, state):
        if key == Gdk.KEY_Left:
            self.area.set_view(yaw=self.area.yaw - 5)
        elif key == Gdk.KEY_Right:
            self.area.set_view(yaw=self.area.yaw + 5)
        elif key == Gdk.KEY_Up:
            self.area.set_view(pitch=self.area.pitch + 5)
        elif key == Gdk.KEY_Down:
            self.area.set_view(pitch=self.area.pitch - 5)
        elif key in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.area.set_view(fov=self.area.fov / 1.15)
        elif key in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.area.set_view(fov=self.area.fov * 1.15)
        elif key == Gdk.KEY_Home:
            self.reset()
        elif key == Gdk.KEY_F11:
            self.fullscreen()
        elif key == Gdk.KEY_Escape:
            self.window.unfullscreen()
        elif state & Gdk.ModifierType.CONTROL_MASK and key == Gdk.KEY_o:
            self.choose_file()
        elif state & Gdk.ModifierType.CONTROL_MASK and key == Gdk.KEY_s:
            self.choose_snapshot()
        else:
            return False
        return True

    def smoke_poll(self):
        if self.smoke_error:
            return False
        if not self.area.panorama or not hasattr(self.area, 'layout'):
            return True
        side, scale, w, h, cols, rows = self.area.layout
        if self.area.loaded_pages != cols*rows:
            return True
        if self.smoke_stage == 0:
            try:
                # Exercise the same handlers used by GTK controllers before
                # capturing a fixed view for CPU/GPU comparison.
                old_yaw = self.area.yaw
                self.drag_begin(None, 0, 0)
                self.drag_update(None, 50, -20)
                assert self.area.yaw != old_yaw, 'Drag did not rotate the camera'
                old_fov = self.area.fov
                self.scroll(None, 0, -1)
                assert self.area.fov < old_fov, 'Scroll did not zoom the camera'
                assert self.key(None, Gdk.KEY_Home, 0, Gdk.ModifierType(0))
            except Exception as error:
                self.error(f'Проверка управления: {error}')
                return False
            self.area.set_view(self.args.yaw if self.args.yaw is not None else 60.583633,
                               self.args.pitch if self.args.pitch is not None else -7.411967,
                               self.args.fov if self.args.fov is not None else 60)
            self.area.snapshot_path = str(Path(self.args.smoke_test).resolve())
            self.area.queue_render()
            self.smoke_stage = 1
            return True
        if self.area.snapshot_path is None:
            print(f'GTK/OpenGL OK: {w}x{h}, {cols*rows} pages, {len(self.area.failed_tiles)} missing tiles')
            self.area._cancel()
            self.quit()
            return False
        return True

    def smoke_timeout(self):
        self.smoke_error = 'GTK smoke test timed out'
        self.quit()
        return False
