#!/usr/bin/env python3
"""Globe export settings and background PDF generation for GTK."""
import threading
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from .globe import GlobeSettings
from .ui import FileDialog


class GlobeExportController:
    def __init__(self, viewer):
        self.viewer = viewer
        self.busy = False

    def choose(self, *arguments):
        if not self.busy and self.viewer.area.panorama:
            GlobeSettingsDialog(self, self.viewer.area.panorama, self.viewer.area.yaw).present()

    def start(self, panorama, settings, path):
        if self.busy:
            return
        self.busy = True
        self.viewer.status.set_text('Генерация PDF для шара…')
        threading.Thread(target=self._export, args=(panorama, settings, path), daemon=True).start()

    def _export(self, panorama, settings, path):
        try:
            from .globe_pdf import GlobePdf
            destination = GlobePdf(panorama, settings).save(path)
            GLib.idle_add(self._finished, str(destination), None)
        except Exception as error:
            GLib.idle_add(self._finished, None, str(error))

    def _finished(self, path, error):
        self.busy = False
        if error:
            self.viewer.error(error)
        else:
            self.viewer.status.set_text(f'PDF сохранён: {path}. Печать: 100%, без подгонки.')
        return False


class GlobeSettingsDialog:
    def __init__(self, controller, panorama, yaw):
        self.controller, self.panorama = controller, panorama
        self.dialog = Gtk.Dialog(title='Панорама на шаре', transient_for=controller.viewer.window, modal=True)
        self.dialog.add_button('Отмена', Gtk.ResponseType.CANCEL)
        self.dialog.add_button('Сохранить PDF…', Gtk.ResponseType.ACCEPT)
        self.dialog.connect('response', self._response)
        self._content(yaw)

    def _content(self, yaw):
        box = self.dialog.get_content_area()
        box.set_spacing(12)
        self._margins(box)
        self.diameter = self._spin(box, 'Диаметр готового шара, мм', 20, 150, 1, 100, 1)
        self.gores = self._spin(box, 'Количество лепестков', 12, 48, 1, 24)
        self.dpi = self._spin(box, 'Разрешение, DPI', 72, 600, 1, 300)
        self.yaw = self._spin(box, 'Азимут центра первого лепестка, °', 0, 360, 1, yaw % 360, 1)
        self._instructions(box)

    @staticmethod
    def _margins(box):
        box.set_margin_start(18)
        box.set_margin_end(18)
        box.set_margin_top(18)
        box.set_margin_bottom(18)

    @staticmethod
    def _spin(box, title, minimum, maximum, step, value, digits=0):
        row = Gtk.Box(spacing=20)
        label = Gtk.Label(label=title, xalign=0, hexpand=True)
        spin = Gtk.SpinButton.new_with_range(minimum, maximum, step)
        spin.set_digits(digits)
        spin.set_value(value)
        row.append(label)
        row.append(spin)
        box.append(row)
        return spin

    @staticmethod
    def _instructions(box):
        label = Gtk.Label(label='A4 · масштаб 100% · контрольная линейка 50 мм\n'
                          'Лепестки клеятся встык, без клапанов. Серое — неснятая область.\n'
                          'Узкие лепестки уменьшают складки. Сначала проверьте один на бумаге.\n'
                          'Экспорт использует всю панораму; наклон и масштаб камеры не влияют.', xalign=0)
        label.set_wrap(True)
        label.set_max_width_chars(65)
        box.append(label)

    def present(self):
        self.dialog.present()

    def _response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            self.settings = GlobeSettings(self.diameter.get_value(), self.gores.get_value_as_int(),
                                          self.dpi.get_value_as_int(), self.yaw.get_value())
            self._destination()
        dialog.destroy()

    def _destination(self):
        parent = self.controller.viewer.window
        chooser = FileDialog(parent, 'Сохранить развёртку', Gtk.FileChooserAction.SAVE, 'Сохранить', self._save)
        chooser.dialog.set_current_name(f'{self.panorama.image_id}_globe_{self.settings.diameter:g}mm.pdf')
        chooser.dialog.show()

    def _save(self, path):
        self.controller.start(self.panorama, self.settings, path)
