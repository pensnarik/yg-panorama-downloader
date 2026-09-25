#!/usr/bin/env python3
"""Collapsible GTK4 sidebar for panorama metadata and viewer status."""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Pango, Gdk
from .history_ui import HistoryPanel


class MetadataPanel:
    def __init__(self, viewer):
        self.viewer = viewer
        PanelStyle.install()
        self.revealer = Gtk.Revealer(reveal_child=True, hexpand=False)
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self.revealer.set_transition_duration(180)
        self.revealer.set_child(self._content())
        self.button = Gtk.ToggleButton(icon_name='sidebar-hide-symbolic', active=True)
        self.button.set_tooltip_text('Показать или скрыть сведения о панораме')
        self.button.connect('toggled', self._toggle)

    def _content(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(310, -1)
        scroll.add_css_class('panorama-sidebar')
        scroll.set_child(self._blocks())
        return scroll

    def _blocks(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('start', 'end', 'top', 'bottom'):
            getattr(box, 'set_margin_' + side)(16)
        PanelControls(self.viewer).populate(box)
        self._populate(box)
        return box

    def _populate(self, box):
        viewer = self.viewer
        self._marker_control(box)
        viewer.status = self._section(box, 'Панорама', 'Откройте панораму для просмотра.', 'image-x-generic-symbolic')
        viewer.view_label = self._section(box, 'Направление', 'Азимут · наклон · обзор', 'find-location-symbolic')
        self._section(box, 'Управление', 'Перетаскивание — поворот\nКолесо — масштаб\nHome — исходный вид\nF11 — полный экран', 'input-mouse-symbolic')

    def _marker_control(self, box):
        card = self.card(box, 'Подписи на панораме', 'mark-location-symbolic')
        self.viewer.marker_toggle = Gtk.CheckButton(label='Маркеры', active=False)
        self.viewer.marker_toggle.set_tooltip_text('Номера домов и подписи из метаданных. Видны сквозь объекты.')
        card.append(self.viewer.marker_toggle)
        self.viewer.navigation_toggle = Gtk.CheckButton(label='Переходы', active=True)
        card.append(self.viewer.navigation_toggle)

    @staticmethod
    def _title(box):
        title = Gtk.Label(label='Панорамы', xalign=0)
        title.add_css_class('panorama-panel-title')
        box.append(title)
        caption = Gtk.Label(label='Сведения и параметры просмотра', xalign=0)
        caption.add_css_class('dim-label')
        box.append(caption)

    @classmethod
    def _section(cls, box, title, text, icon):
        card = cls.card(box, title, icon)
        label = cls._label(text)
        card.append(label)
        return label

    @classmethod
    def card(cls, box, title, icon):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class('panorama-info-card')
        card.append(cls._heading(title, icon))
        box.append(card)
        return card

    @staticmethod
    def _heading(title, icon):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class('panorama-card-heading')
        row.append(Gtk.Image.new_from_icon_name(icon))
        row.append(Gtk.Label(label=title, xalign=0))
        return row

    @staticmethod
    def _label(text):
        label = Gtk.Label(label=text, xalign=0, wrap=True, selectable=False)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_max_width_chars(30)
        label.set_width_chars(25)
        label.add_css_class('panorama-card-value')
        return label

    def _toggle(self, button):
        self.revealer.set_reveal_child(button.get_active())
        self.button.set_icon_name('sidebar-hide-symbolic' if button.get_active() else 'sidebar-show-symbolic')


class PanelControls:
    def __init__(self, viewer):
        self.viewer = viewer

    def populate(self, box):
        self._actions(box)
        MetadataPanel._title(box)
        self._library(MetadataPanel.card(box, 'Библиотека', 'folder-open-symbolic'))
        self.viewer.history = HistoryPanel(self.viewer, MetadataPanel.card(box, 'Другие даты', 'x-office-calendar-symbolic'))
        self.viewer.sky.add_controls(MetadataPanel.card(box, 'Небо и время', 'weather-clear-symbolic'))

    def _library(self, box):
        self._button(box, 'Открыть…', self.viewer.choose_file)
        selector = Gtk.DropDown.new_from_strings([])
        selector.set_enable_search(True)
        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', self._setup_item)
        factory.connect('bind', self._bind_item)
        selector.set_factory(factory)
        self._connect_selector(selector)
        box.append(selector)

    def _connect_selector(self, selector):
        selector.connect('notify::selected', self.viewer.select_panorama)
        self.viewer.selector = selector

    @staticmethod
    def _setup_item(factory, item):
        item.set_child(Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=24))

    @staticmethod
    def _bind_item(factory, item):
        text = item.get_item().get_string()
        item.get_child().set_text(text)
        item.get_child().set_tooltip_text(text)

    def _actions(self, box):
        viewer = self.viewer
        rows = [Gtk.Box(spacing=6), Gtk.Box(spacing=6)]
        self._button(rows[0], 'Сброс', viewer.reset, 'view-refresh-symbolic', 'Сбросить вид · Home')
        self._button(rows[0], 'Экран', viewer.fullscreen, 'view-fullscreen-symbolic', 'Полный экран · F11')
        self._button(rows[1], 'Снимок', viewer.choose_snapshot, 'camera-photo-symbolic', 'Сохранить вид · Ctrl+S')
        self._button(rows[1], 'На шар', viewer.globe_export.choose, 'document-print-symbolic', 'Развёртка для печати на шар')
        for row in rows:
            box.append(row)

    @staticmethod
    def _button(box, title, callback, icon='folder-open-symbolic', tooltip=None):
        button = Gtk.Button(hexpand=True, tooltip_text=tooltip or title)
        content = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        content.append(Gtk.Image.new_from_icon_name(icon))
        content.append(Gtk.Label(label=title))
        button.set_child(content)
        button.connect('clicked', callback)
        box.append(button)


class PanelStyle:
    CSS = b"""
    .panorama-sidebar button.panorama-current-year:disabled {
        background-image: none; background-color: #1c71d8; color: white;
        border-color: #1a5fb4; opacity: 1; font-weight: 700;
        box-shadow: none; text-shadow: none;
    }
    .panorama-sidebar button.panorama-current-year:disabled label { color: white; opacity: 1; }
    .panorama-transition { min-width: 24px; min-height: 34px; padding: 4px 9px;
        border-radius: 24px; background: #174f7b; color: white; font-size: 20px; }
    .panorama-transition.panorama-unavailable, .panorama-transition:disabled { background: #555; color: #bbb; }
    .panorama-marker {
        background: rgba(20, 27, 38, 0.88); color: white;
        border: 1px solid rgba(255, 255, 255, 0.7); border-radius: 8px;
        padding: 5px 9px; font-size: 14px; font-weight: 600;
    }
    .panorama-sidebar {
        background-color: @theme_bg_color;
        border-right: 1px solid alpha(@theme_fg_color, 0.12);
    }
    .panorama-panel-title { font-size: 20px; font-weight: 700; margin-top: 4px; }
    .panorama-info-card {
        padding: 16px; border-radius: 12px;
        background-color: alpha(@theme_base_color, 0.65);
        border: 1px solid alpha(@theme_fg_color, 0.10);
        box-shadow: 0 2px 4px alpha(black, 0.04);
    }
    .panorama-card-heading { color: alpha(@theme_fg_color, 0.65); font-weight: 600; }
    .panorama-card-heading image { color: @theme_selected_bg_color; }
    .panorama-card-value { font-size: 13px; }
    """

    @classmethod
    def install(cls):
        provider = Gtk.CssProvider()
        provider.load_from_data(cls.CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
