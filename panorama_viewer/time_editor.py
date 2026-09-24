#!/usr/bin/env python3
"""GTK4 calendar dialog and synchronized inline UTC time controls."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib


class SkyTimeEditor:
    def __init__(self, controller, box):
        self.controller, self.updating, self.typing = controller, False, False
        self.date = controller.time.text().split()[0]
        self.date_button = Gtk.Button(label=self.date)
        self.date_button.connect('clicked', self.choose_date)
        box.append(self.date_button)
        self._clock(box)
        self.sync()

    def _clock(self, box):
        self.time_entry = Gtk.Entry(placeholder_text='ЧЧ:ММ:СС', input_purpose=Gtk.InputPurpose.FREE_FORM)
        self.time_entry.set_tooltip_text('Время в выбранном часовом поясе: ЧЧ:ММ или ЧЧ:ММ:СС')
        self.time_entry.connect('changed', self._typed)
        box.append(self.time_entry)
        self.slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 86399, 1)
        self.slider.set_draw_value(False)
        self.slider.set_tooltip_text('Время суток в выбранном поясе: от 00:00:00 до 23:59:59')
        self.slider.connect('value-changed', self._slid)
        box.append(self.slider)

    def sync(self):
        self.updating = True
        try:
            self.date, clock = self.controller.time.text().split()
            self.date_button.set_label(self.date)
            self._display_clock(clock)
            hours, minutes, seconds = map(int, clock.split(':'))
            self.slider.set_value(hours * 3600 + minutes * 60 + seconds)
        finally:
            self.updating = False

    def _display_clock(self, clock):
        if not self.typing:
            self.time_entry.set_text(clock)

    def _typed(self, entry):
        if not self.updating:
            clock = entry.get_text().strip()
            clock += ':00' if clock.count(':') == 1 else ''
            self.typing = True
            try:
                self.controller.change_time(f'{self.date} {clock}')
            finally:
                self.typing = False

    def _slid(self, slider):
        if not self.updating:
            seconds = round(slider.get_value())
            clock = f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'
            self.controller.change_time(f'{self.date} {clock}')

    def choose_date(self, *arguments):
        dialog = Gtk.Dialog(title='Дата расчёта · UTC', transient_for=self.controller.viewer.window, modal=True)
        dialog.add_button('Отмена', Gtk.ResponseType.CANCEL)
        dialog.add_button('Выбрать', Gtk.ResponseType.OK)
        calendar = Gtk.Calendar()
        calendar.select_day(GLib.DateTime.new_from_iso8601(self.date + 'T12:00:00Z', None))
        dialog.get_content_area().append(calendar)
        dialog.connect('response', self._date_response, calendar)
        dialog.present()

    def _date_response(self, dialog, response, calendar):
        if response == Gtk.ResponseType.OK:
            date = calendar.get_date().format('%Y-%m-%d')
            clock = self.controller.time.text().split()[1]
            self.controller.change_time(f'{date} {clock}')
        dialog.destroy()
