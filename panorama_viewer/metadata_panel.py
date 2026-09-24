#!/usr/bin/env python3
"""Collapsible GTK4 sidebar for panorama metadata."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Pango


class MetadataPanel:
    def __init__(self, viewer):
        self.viewer = viewer
        self.revealer = Gtk.Revealer(reveal_child=True)
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self.revealer.set_child(self._content())
        self.button = Gtk.ToggleButton(icon_name='sidebar-hide-symbolic', active=True)
        self.button.set_tooltip_text('Показать или скрыть сведения о панораме')
        self.button.connect('toggled', self._toggle)

    def _content(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(290, -1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('start', 'end', 'top', 'bottom'):
            getattr(box, 'set_margin_' + side)(16)
        scroll.set_child(box)
        self._populate(box)
        return scroll

    def _populate(self, box):
        self.viewer.shooting_label = self._section(box, 'Съёмка', 'Дата и время неизвестны')
        self.viewer.status = self._section(box, 'Панорама', 'Откройте панораму.')
        self.viewer.view_label = self._section(box, 'Направление', 'Мышь · колесо · стрелки · Home · F11')

    @staticmethod
    def _section(box, title, text):
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class('heading')
        box.append(heading)
        label = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_max_width_chars(30)
        label.set_width_chars(25)
        box.append(label)
        return label

    def _toggle(self, button):
        self.revealer.set_reveal_child(button.get_active())
