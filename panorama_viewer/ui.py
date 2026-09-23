#!/usr/bin/env python3
"""GTK window construction, dialogs and input adapters."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk
from .gl import PanoramaArea


class WindowBuilder:
    def __init__(self, viewer):
        self.viewer = viewer

    def build(self):
        viewer = self.viewer
        viewer.window = Gtk.ApplicationWindow(application=viewer, title='Панорамы · офлайн')
        viewer.window.set_default_size(1180, 800)
        viewer.window.connect('close-request', viewer.close_viewer)
        self._header()
        self._body()

    def _header(self):
        header = Gtk.HeaderBar()
        self.viewer.window.set_titlebar(header)
        self._open_controls(header)
        self._view_controls(header)

    def _open_controls(self, header):
        viewer = self.viewer
        header.pack_start(self._button('Открыть…', None, viewer.choose_file))
        viewer.selector = Gtk.DropDown.new_from_strings([])
        viewer.selector.set_tooltip_text('Локальные панорамы с metadata.json')
        viewer.selector.connect('notify::selected', viewer.select_panorama)
        header.pack_start(viewer.selector)

    def _view_controls(self, header):
        viewer = self.viewer
        header.pack_end(self._button('Сбросить вид', None, viewer.reset))
        header.pack_end(self._button(None, 'view-fullscreen-symbolic', viewer.fullscreen, 'Полный экран · F11'))
        header.pack_end(self._button(None, 'camera-photo-symbolic', viewer.choose_snapshot, 'Сохранить вид · Ctrl+S'))

    @staticmethod
    def _button(label, icon, callback, tooltip=None):
        button = Gtk.Button(label=label) if label else Gtk.Button(icon_name=icon)
        button.connect('clicked', callback)
        if tooltip:
            button.set_tooltip_text(tooltip)
        return button

    def _body(self):
        viewer = self.viewer
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        viewer.window.set_child(box)
        self._labels()
        viewer.area = PanoramaArea(viewer.args.gpu_memory, viewer.status.set_text, viewer.error, viewer.update_view)
        for widget in (viewer.area, viewer.status, viewer.view_label):
            box.append(widget)

    def _labels(self):
        viewer = self.viewer
        viewer.status = Gtk.Label(label='Откройте metadata.json или выберите панораму.', xalign=0)
        viewer.status.set_selectable(True)
        viewer.status.set_wrap(True)
        self._status_margins()
        viewer.view_label = Gtk.Label(label='Мышь · колесо · стрелки · Home · F11')
        viewer.view_label.set_margin_bottom(8)

    def _status_margins(self):
        status = self.viewer.status
        status.set_margin_start(12)
        status.set_margin_end(12)
        status.set_margin_top(6)
        status.set_margin_bottom(6)


class FileDialog:
    def __init__(self, parent, title, action, accept_label, on_accept):
        self.dialog = Gtk.FileChooserNative.new(title, parent, action, accept_label, 'Отмена')
        self.on_accept = on_accept
        self.dialog.connect('response', self._response)

    def _response(self, chooser, result):
        try:
            if result == Gtk.ResponseType.ACCEPT:
                self.on_accept(chooser.get_file().get_path())
        finally:
            chooser.destroy()

    @classmethod
    def open_metadata(cls, viewer):
        dialog = cls(viewer.window, 'Открыть метаданные', Gtk.FileChooserAction.OPEN, 'Открыть', viewer.open_path)
        file_filter = Gtk.FileFilter()
        file_filter.set_name('Метаданные JSON')
        file_filter.add_pattern('*.json')
        dialog.dialog.add_filter(file_filter)
        dialog.dialog.show()

    @classmethod
    def save_snapshot(cls, viewer):
        if viewer.area.panorama:
            dialog = cls(viewer.window, 'Сохранить вид', Gtk.FileChooserAction.SAVE, 'Сохранить', viewer.save_snapshot)
            dialog.dialog.set_current_name(f'{viewer.area.panorama.image_id}_view.png')
            dialog.dialog.show()


class ViewerControls:
    def __init__(self, viewer):
        self.viewer = viewer
        self.area = viewer.area
        self._drag_controller()
        self._scroll_controller()
        controller = Gtk.EventControllerKey.new()
        controller.connect('key-pressed', self.key)
        viewer.window.add_controller(controller)

    def _drag_controller(self):
        gesture = Gtk.GestureDrag.new()
        gesture.set_button(1)
        gesture.connect('drag-begin', self.drag_begin)
        gesture.connect('drag-update', self.drag_update)
        self.area.add_controller(gesture)

    def _scroll_controller(self):
        controller = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        controller.connect('scroll', self.scroll)
        self.area.add_controller(controller)

    def drag_begin(self, controller, horizontal, vertical):
        self.area.grab_focus()
        self.area.camera.begin_drag()

    def drag_update(self, controller, horizontal, vertical):
        self.area.camera.drag(horizontal, vertical, self.area.get_height())
        self.area.view_changed()

    def scroll(self, controller, horizontal, vertical):
        self.area.camera.scroll(vertical)
        self.area.view_changed()
        return True

    def key(self, controller, key, code, state):
        changes = self._camera_keys()
        if key in changes:
            self.area.set_view(**changes[key])
            return True
        actions = self._actions(state)
        if key in actions:
            actions[key]()
            return True
        return False

    def _camera_keys(self):
        camera = self.area.camera
        changes = {Gdk.KEY_Left: {'yaw': camera.yaw-5}, Gdk.KEY_Right: {'yaw': camera.yaw+5},
                   Gdk.KEY_Up: {'pitch': camera.pitch+5}, Gdk.KEY_Down: {'pitch': camera.pitch-5}}
        for key in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            changes[key] = {'fov': camera.fov / 1.15}
        for key in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            changes[key] = {'fov': camera.fov * 1.15}
        return changes

    def _actions(self, state):
        viewer = self.viewer
        actions = {Gdk.KEY_Home: viewer.reset, Gdk.KEY_F11: viewer.fullscreen,
                   Gdk.KEY_Escape: viewer.window.unfullscreen}
        if state & Gdk.ModifierType.CONTROL_MASK:
            actions.update({Gdk.KEY_o: viewer.choose_file, Gdk.KEY_s: viewer.choose_snapshot})
        return actions
