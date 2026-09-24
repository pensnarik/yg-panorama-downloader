#!/usr/bin/env python3
"""Optional live sky controls; calculations stay independent of camera movement."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from .sky_time import SkyTime
from .time_editor import SkyTimeEditor


class SkyController:
    def __init__(self, viewer):
        self.viewer = viewer
        self.timer = None
        self.time = SkyTime()
        self.time_valid = True

    def add_controls(self, box):
        self._populate(box)

    def _populate(self, box):
        self.viewer.shooting_label = Gtk.Label(label='Дата и время · UTC', xalign=0)
        box.append(self.viewer.shooting_label)
        self.editor = SkyTimeEditor(self, box)
        self.time_hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=30)
        box.append(self.time_hint)
        self._time_buttons(box)
        self.sun = self._toggle(box, 'Солнце')
        self.moon = self._toggle(box, 'Луна')
        self._details(box)

    def _details(self, box):
        self.label = Gtk.Label(label='ⓘ Расчётные данные', xalign=0)
        self.label.add_css_class('dim-label')
        self.label.set_tooltip_text('Включите Солнце или Луну, чтобы посмотреть расчётные данные.')
        box.append(self.label)

    def _time_buttons(self, box):
        for title, callback in (('Из метаданных', self.select_panorama), ('Сейчас', self._now)):
            button = Gtk.Button(label=title)
            button.connect('clicked', callback)
            box.append(button)

    def select_panorama(self, *arguments):
        panorama = self.viewer.area.panorama
        if panorama is not None:
            self.time.from_metadata(panorama.shooting_date)
            self._show_time()

    def _show_time(self):
        self.time_valid = True
        self.editor.sync()
        self.time_hint.set_text(self.time.explanation)
        self.refresh()

    def _now(self, *arguments):
        self.time.timestamp = None
        self._show_time()
        self.time.timestamp = None
        self.time.explanation = 'Текущее время; обновление раз в минуту'
        self.time_hint.set_text(self.time.explanation)
        self.refresh()

    def _time_changed(self, entry):
        self.change_time(entry.get_text())

    def change_time(self, text):
        try:
            self.time.set_text(text)
            self.time_valid = True
        except ValueError:
            self._invalid_time()
            return
        self._sync_time()

    def _sync_time(self):
        if hasattr(self, 'editor'):
            self.editor.sync()
        self.time_hint.set_text(self.time.explanation)
        self.refresh()

    def _invalid_time(self):
        self.time_valid = False
        self.time_hint.set_text('Введите время от 00:00:00 до 23:59:59 в выбранном поясе')
        self.viewer.area.sky_overlay = None
        self.viewer.area.queue_render()

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
        if self.time.timestamp is None and (self.sun.get_active() or self.moon.get_active()):
            if hasattr(self, 'editor'):
                self.editor.sync()
            self.refresh()
        return True

    def refresh(self, *arguments):
        self.viewer.area.sky_overlay = None
        self.label.set_text('ⓘ Расчётные данные')
        self.label.set_tooltip_text('Включите Солнце или Луну для расчёта.')
        try:
            if self.time_valid and (self.sun.get_active() or self.moon.get_active()):
                self._calculate()
        except (ImportError, ValueError, TypeError, KeyError, AttributeError) as error:
            self.label.set_text(f'Небо недоступно: {error}')
        self.viewer.area.queue_render()

    def _calculate(self):
        from .astronomy import ObserverLocation, Ephemeris, SkyOverlay
        panorama = self.viewer.area.panorama
        if panorama is None:
            raise ValueError('Сначала откройте панораму')
        snapshot = Ephemeris.calculate(ObserverLocation.from_panorama(panorama), self.time.timestamp)
        self.viewer.area.sky_overlay = SkyOverlay(snapshot, self.sun.get_active(), self.moon.get_active())
        self.label.set_tooltip_text(self._description(snapshot))

    @staticmethod
    def _description(snapshot):
        return (f'Расчёт: {snapshot.timestamp:%Y-%m-%d %H:%M:%S} UTC\n'
                f'{snapshot.sun.description("Солнце")}\n{snapshot.moon.description("Луна")}\n'
                f'Луна освещена на {snapshot.moon_fraction:.0%}.\n'
                'Горизонт: 0°. Без рефракции; высота места: 0 м.\n'
                'Наложение видно сквозь объекты и ниже горизонта.')
