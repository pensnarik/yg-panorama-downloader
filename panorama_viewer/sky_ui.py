#!/usr/bin/env python3
"""Optional live sky controls; calculations stay independent of camera movement."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib


class SkyController:
    def __init__(self, viewer):
        self.viewer = viewer
        self.timer = None

    def add_controls(self, header):
        button = Gtk.MenuButton(label='Небо')
        popover = Gtk.Popover()
        box = self._box()
        popover.set_child(box)
        button.set_popover(popover)
        header.pack_end(button)
        self._populate(box)

    @staticmethod
    def _box():
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_start(14)
        box.set_margin_end(14)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        return box

    def _populate(self, box):
        self.sun = self._toggle(box, 'Солнце')
        self.moon = self._toggle(box, 'Луна')
        self.label = Gtk.Label(label='Текущее время · реальный угловой размер\n'
                               'Горизонт 0° виден вместе со светилами.\n'
                               'Наложение видно сквозь здания и ниже горизонта.', xalign=0)
        self.label.set_wrap(True)
        self.label.set_max_width_chars(55)
        box.append(self.label)

    def _toggle(self, box, title):
        toggle = Gtk.CheckButton(label=title)
        toggle.connect('toggled', self.refresh)
        box.append(toggle)
        return toggle

    def start(self):
        self.timer = GLib.timeout_add_seconds(60, self._tick)

    def close(self):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None

    def _tick(self):
        if self.sun.get_active() or self.moon.get_active():
            self.refresh()
        return True

    def refresh(self, *arguments):
        self.viewer.area.sky_overlay = None
        try:
            if self.sun.get_active() or self.moon.get_active():
                self._calculate()
        except (ImportError, ValueError, TypeError, KeyError, AttributeError) as error:
            self.label.set_text(f'Небо недоступно: {error}')
        self.viewer.area.queue_render()

    def _calculate(self):
        from .astronomy import ObserverLocation, Ephemeris, SkyOverlay
        panorama = self.viewer.area.panorama
        if panorama is None:
            raise ValueError('Сначала откройте панораму')
        snapshot = Ephemeris.calculate(ObserverLocation.from_panorama(panorama))
        self.viewer.area.sky_overlay = SkyOverlay(snapshot, self.sun.get_active(), self.moon.get_active())
        self.label.set_text(self._description(snapshot))

    @staticmethod
    def _description(snapshot):
        return (f'Сейчас: {snapshot.timestamp:%Y-%m-%d %H:%M:%S} UTC\n'
                f'{snapshot.sun.description("Солнце")}\n{snapshot.moon.description("Луна")}\n'
                f'Луна освещена на {snapshot.moon_fraction:.0%}. Обновление раз в минуту.\n'
                'Горизонт: 0°. Без рефракции; высота места: 0 м.\n'
                'Наложение видно сквозь объекты и ниже горизонта.')
