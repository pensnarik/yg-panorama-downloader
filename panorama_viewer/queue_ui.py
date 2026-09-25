#!/usr/bin/env python3
"""Nonblocking queue submission from unavailable panorama arrows."""
from threading import Thread
import psycopg
from gi.repository import GLib
from panorama_archive.queue import DownloadQueue


class QueueController:
    def __init__(self, viewer):
        self.viewer = viewer
        self.pending = set()

    def submit(self, button, identifier):
        if identifier in self.pending:
            return
        self.pending.add(identifier)
        button.set_sensitive(False)
        button.set_tooltip_text('Добавление в очередь…')
        source = self.viewer.area.panorama.panorama_id
        Thread(target=self._submit, args=(button, identifier, source), daemon=True).start()

    def _submit(self, button, identifier, source):
        try:
            result = DownloadQueue().enqueue(identifier, source)
            message = 'Скачивается' if result['status'] == 'downloading' else 'В очереди на скачивание'
            GLib.idle_add(self._finished, button, identifier, message, True)
        except (psycopg.Error, ValueError):
            GLib.idle_add(self._finished, button, identifier, 'Не удалось добавить в очередь: проверьте БД и миграцию V005.', False)

    def _finished(self, button, identifier, message, success):
        self.pending.discard(identifier)
        if self.viewer.library.closed:
            return False
        button.set_sensitive(True)
        button.set_tooltip_text(message + (' · повторный клик проверит очередь' if success else ''))
        if success:
            button.set_label('⌛')
        self.viewer.status.set_text(message)
        return False
