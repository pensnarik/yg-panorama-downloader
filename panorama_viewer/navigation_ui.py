#!/usr/bin/env python3
"""Clickable offline panorama transitions over the GTK panorama viewport."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from .markers import MarkerGeometry, MarkerPlacement
from .navigation import LocalPanoramaIndex, PanoramaConnections


class NavigationOverlay:
    def __init__(self, viewer, overlay):
        self.viewer, self.overlay = viewer, overlay
        self.previous, self.buttons, self.index = None, [], {}
        viewer.area.add_tick_callback(self._tick)

    def _tick(self, widget, clock):
        area = self.viewer.area
        state = (area.panorama, tuple(self.viewer.library.paths), area.yaw, area.pitch, area.fov,
                 area.get_width(), area.get_height(), self.viewer.navigation_toggle.get_active())
        if state != self.previous:
            if self.previous is None or state[:2] != self.previous[:2]:
                self._load()
            self.previous = state
            self._layout()
        return True

    def _load(self):
        for link, button in self.buttons:
            self.overlay.remove_overlay(button)
        self.buttons = []
        self.index = LocalPanoramaIndex.build(self.viewer.library.paths)
        if self.viewer.area.panorama:
            for link in PanoramaConnections.read(self.viewer.area.panorama):
                self._button(link)

    def _button(self, link):
        available = link.identifier in self.index
        button = Gtk.Button(label='➜', halign=Gtk.Align.START, valign=Gtk.Align.START)
        button.add_css_class('panorama-transition')
        button.set_sensitive(available)
        button.set_tooltip_text(link.name + (' · перейти' if available else ' · не скачана'))
        button.connect('clicked', self._navigate, link.identifier)
        self.overlay.add_overlay(button)
        self.buttons.append((link, button))

    def _layout(self):
        occupied = []
        for link, button in self.buttons:
            rectangle = self._place(link) if self.viewer.navigation_toggle.get_active() else None
            button.set_visible(rectangle is not None and not any(MarkerPlacement.overlaps(rectangle, item) for item in occupied))
            if button.get_visible():
                button.set_margin_start(round(rectangle[0]))
                button.set_margin_top(round(rectangle[1]))
                occupied.append(rectangle)

    def _place(self, link):
        area = self.viewer.area
        viewport = area.get_width(), area.get_height()
        center = MarkerGeometry.screen(link, area.camera, *viewport)
        return MarkerPlacement.rectangle(center, (44, 44), viewport, []) if center else None

    def _navigate(self, button, identifier):
        path = self.index.get(identifier)
        if path is None:
            return
        camera = self.viewer.area.camera
        direction = camera.yaw, camera.pitch, camera.fov
        self.viewer.open_path(path)
        self.viewer.area.set_view(*direction)
