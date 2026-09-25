#!/usr/bin/env python3
"""Non-interactive GTK overlay with screen-space label collision avoidance."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Pango
from .markers import MarkerGeometry, MarkerPlacement
from .marker_snapshot import MarkerSnapshot


class MarkerOverlay(Gtk.Fixed):
    def __init__(self, viewer):
        super().__init__(can_target=False)
        self.viewer, self.panorama = viewer, None
        self.labels, self.visible, self.previous = [], [], None
        self.add_tick_callback(self._tick)
        viewer.area.set_has_tooltip(True)
        viewer.area.connect('query-tooltip', self._tooltip)
        viewer.area.marker_snapshot = self.save_snapshot

    def _tick(self, widget, clock):
        area = self.viewer.area
        state = (area.panorama, area.yaw, area.pitch, area.fov, self.get_width(), self.get_height(),
                 self.viewer.marker_toggle.get_active())
        if state != self.previous:
            self.previous = state
            if self.panorama is not area.panorama:
                self._load(area.panorama)
            self._layout()
        return True

    def _load(self, panorama):
        for marker, label in self.labels:
            self.remove(label)
        self.panorama, self.labels, self.sizes = panorama, [], {}
        for marker in panorama.markers if panorama else []:
            label = Gtk.Label(label=marker.name, ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
            label.add_css_class('panorama-marker')
            self.put(label, 0, 0)
            self.labels.append((marker, label))

    def _layout(self):
        self.visible = []
        occupied = []
        for marker, label in self.labels:
            label.set_visible(True)
            rectangle = self._place(marker, label, occupied) if self.viewer.marker_toggle.get_active() else None
            label.set_visible(rectangle is not None)
            if rectangle:
                self._show(marker, label, rectangle, occupied)

    def _show(self, marker, label, rectangle, occupied):
        self.move(label, rectangle[0], rectangle[1])
        occupied.append(rectangle)
        self.visible.append((rectangle, marker))

    def _place(self, marker, label, occupied):
        viewport = self.get_width(), self.get_height()
        center = MarkerGeometry.screen(marker, self.viewer.area.camera, *viewport)
        if center is None:
            return None
        return MarkerPlacement.rectangle(center, self._size(label), viewport, occupied)

    def _size(self, label):
        if label not in self.sizes:
            width = label.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            self.sizes[label] = (width, label.measure(Gtk.Orientation.VERTICAL, width)[1])
            label.set_size_request(*self.sizes[label])
        return self.sizes[label]

    def save_snapshot(self, path):
        entries, occupied = [], []
        if not self.viewer.marker_toggle.get_active() or self.panorama is not self.viewer.area.panorama:
            return
        for marker, label in self.labels:
            rectangle = self._place(marker, label, occupied)
            if rectangle:
                occupied.append(rectangle)
                entries.append((rectangle, marker))
        MarkerSnapshot.save(path, entries, self.get_width())

    def _tooltip(self, area, horizontal, vertical, keyboard, tooltip):
        if keyboard:
            return False
        for (left, top, width, height), marker in self.visible:
            if left <= horizontal <= left + width and top <= vertical <= top + height:
                tooltip.set_text(marker.description)
                return True
        return False
