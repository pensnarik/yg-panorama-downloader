#!/usr/bin/env python3
"""Compact year buttons for switching between saved historical panoramas."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from .history import PanoramaHistory
from .navigation import LocalPanoramaIndex


class HistoryPanel:
    def __init__(self, viewer, box):
        self.viewer, self.index = viewer, {}
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self.rows)
        self.buttons = []

    def refresh(self):
        while self.rows.get_first_child():
            self.rows.remove(self.rows.get_first_child())
        self.buttons = []
        self.index = LocalPanoramaIndex.build(self.viewer.library.paths)
        panorama = self.viewer.area.panorama
        links = PanoramaHistory.read(panorama) if panorama else []
        if not links:
            self.rows.append(Gtk.Label(label='Другие даты не указаны', xalign=0, wrap=True))
        self._populate(links, panorama)

    def _populate(self, links, panorama):
        for index, link in enumerate(links):
            if index % 3 == 0:
                row = Gtk.Box(spacing=6, homogeneous=True)
                self.rows.append(row)
            button = self._button(link, panorama.panorama_id)
            row.append(button)
            self.buttons.append((link, button))

    def _button(self, link, current):
        selected = link.identifier == current
        available = link.identifier in self.index
        button = Gtk.Button(label=link.label, hexpand=True)
        button.set_sensitive(available and not selected)
        if selected:
            button.add_css_class('panorama-current-year')
        button.set_tooltip_text('Текущая панорама' if selected else 'Открыть эту дату' if available else 'Панорама не скачана')
        button.connect('clicked', self._open, link.identifier)
        return button

    def _open(self, button, identifier):
        path = self.index.get(identifier)
        if path is None:
            return
        area = self.viewer.area
        direction = area.yaw, area.pitch, area.fov
        self.viewer.open_path(path)
        area.set_view(*direction)
