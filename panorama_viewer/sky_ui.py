#!/usr/bin/env python3
"""Optional live sky controls; calculations stay independent of camera movement."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from .sky_time import SkyTime


class SkyController:
    def __init__(self, viewer):
        self.viewer = viewer
        self.timer = None
        self.time = SkyTime()
        self.time_valid = True

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
        self._time_controls(box)
        self.label = Gtk.Label(label='Выбранное время · реальный угловой размер\n'
                               'Горизонт 0° виден вместе со светилами.\n'
                               'Наложение видно сквозь здания и ниже горизонта.', xalign=0)
        self.label.set_wrap(True)
        self.label.set_max_width_chars(55)
        box.append(self.label)

    def _time_controls(self, box):
        box.append(Gtk.Label(label='Дата и время расчёта (UTC)', xalign=0))
        self.time_entry = Gtk.Entry(text=self.time.text(), placeholder_text='ГГГГ-ММ-ДД ЧЧ:ММ:СС')
        self.time_entry.set_tooltip_text('ГГГГ-ММ-ДД ЧЧ:ММ:СС, UTC. Пересчёт при вводе корректной даты.')
        self.time_entry.connect('changed', self._time_changed)
        box.append(self.time_entry)
        self.time_hint = Gtk.Label(xalign=0, wrap=True)
        box.append(self.time_hint)
        self._time_buttons(box)

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
        explanation = self.time.explanation
        self.time_entry.set_text(self.time.text())
        self.time.explanation = explanation
        self.time_hint.set_text(explanation)
        self.refresh()

    def _now(self, *arguments):
        self.time = SkyTime()
        self._show_time()
        self.time.timestamp = None
        self.time_hint.set_text('Текущее время; обновление раз в минуту')
        self.refresh()

    def _time_changed(self, entry):
        try:
            self.time.set_text(entry.get_text())
            self.time_valid = True
        except ValueError:
            self._invalid_time()
            return
        self.time_hint.set_text(self.time.explanation)
        self.refresh()

    def _invalid_time(self):
        self.time_valid = False
        self.time_hint.set_text('Введите дату и время: ГГГГ-ММ-ДД ЧЧ:ММ:СС (UTC)')
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
            self.refresh()
        return True

    def refresh(self, *arguments):
        self.viewer.area.sky_overlay = None
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
        self.label.set_text(self._description(snapshot))

    @staticmethod
    def _description(snapshot):
        return (f'Расчёт: {snapshot.timestamp:%Y-%m-%d %H:%M:%S} UTC\n'
                f'{snapshot.sun.description("Солнце")}\n{snapshot.moon.description("Луна")}\n'
                f'Луна освещена на {snapshot.moon_fraction:.0%}.\n'
                'Горизонт: 0°. Без рефракции; высота места: 0 м.\n'
                'Наложение видно сквозь объекты и ниже горизонта.')
