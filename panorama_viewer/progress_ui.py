#!/usr/bin/env python3
"""Persistent queue feedback survives recreation of panorama transition buttons."""
from threading import Thread
import psycopg
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from .download_progress import DownloadProgressReader, DownloadState


class QueueProgressController:
    def __init__(self, navigation):
        self.navigation = navigation
        self.states, self.revision, self.busy = {}, 0, False
        GLib.idle_add(self._initial)
        GLib.timeout_add_seconds(30, self.refresh)

    def _initial(self):
        self.refresh()
        return False

    def refresh(self):
        if self.navigation.viewer.library.closed:
            return False
        if not self.busy:
            self.busy = True
            root = self.navigation.viewer.args.library
            Thread(target=self._read, args=(root, self.revision), daemon=True).start()
        return True

    def _read(self, root, revision):
        try:
            states = DownloadProgressReader(root).read()
        except (psycopg.Error, OSError, ValueError):
            states = None
        GLib.idle_add(self._received, states, revision)

    def _received(self, states, revision):
        self.busy = False
        if self.navigation.viewer.library.closed:
            return False
        if states is not None and revision == self.revision:
            self.states = states
            self.navigation.previous = None
        return False

    def submitted(self, identifier):
        old = self.states.get(identifier, DownloadState('pending'))
        self.states[identifier] = DownloadState('pending', old.downloaded, old.total)
        self.revision += 1
        self.navigation.previous = None


class QueueProgressIndicator:
    @staticmethod
    def apply(button, state):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        content.append(Gtk.Label(label='⌛'))
        bar = Gtk.ProgressBar(fraction=state.fraction, width_request=30)
        bar.add_css_class('panorama-download-progress')
        content.append(bar)
        button.set_child(content)
        button.set_tooltip_text(state.tooltip)
