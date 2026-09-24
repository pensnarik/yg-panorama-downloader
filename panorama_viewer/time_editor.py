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
        self._zone_controls(box)
        self._clock(box)
        self.sync()

    def _zone_controls(self, box):
        box.append(Gtk.Label(label='Часовой пояс · смещение от UTC', xalign=0))
        self.offsets = list(range(-720, 841, 15))
        labels = [f'UTC{"+" if value >= 0 else "−"}{abs(value) // 60:02d}:{abs(value) % 60:02d}' for value in self.offsets]
        self.zone_selector = Gtk.DropDown.new_from_strings(labels)
        self.zone_selector.set_enable_search(True)
        self.zone_selector.set_selected(self.offsets.index(self.controller.time.offset_minutes))
        self.zone_selector.connect('notify::selected', self._zone_changed)
        box.append(self.zone_selector)

    def _zone_changed(self, selector, specification):
        self.controller.time.set_offset(self.offsets[selector.get_selected()])
        self.controller.viewer.shooting_label.set_text('Дата и время · ' + self.controller.time.zone_name)
        self.controller.time.explanation = 'Часовой пояс изменён; момент времени сохранён'
        self.controller._show_time()

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
        dialog = Gtk.Dialog(title='Дата расчёта · ' + self.controller.time.zone_name, transient_for=self.controller.viewer.window, modal=True)
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
