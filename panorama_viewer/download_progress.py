#!/usr/bin/env python3
"""Queue state and locally saved tile counts, read outside the GTK thread."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import psycopg
from psycopg.rows import dict_row
from panorama_archive.merge import ArchiveDatabase


@dataclass(frozen=True)
class DownloadState:
    status: str
    downloaded: int = 0
    total: int = 0
    error: str = ''

    @property
    def fraction(self):
        return min(1, self.downloaded / self.total) if self.total else 0

    @property
    def tooltip(self):
        labels = {'pending': 'В очереди', 'downloading': 'Скачивается', 'completed': 'Скачивание завершено',
                  'failed': 'Ошибка; нажмите для повтора'}
        count = f' · {self.downloaded}/{self.total} тайлов' if self.total else ''
        stage = ' · завершение обработки' if self.total and self.downloaded == self.total and self.status == 'downloading' else ''
        return labels.get(self.status, self.status) + count + stage + (f'\n{self.error}' if self.error else '')


class DownloadProgressReader:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()

    def read(self):
        with psycopg.connect(**ArchiveDatabase.SETTINGS, connect_timeout=3,
                             options='-c statement_timeout=5000') as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute('select panorama_id, external_id, status, error_message from aa.panorama_download_queue')
                records = cursor.fetchall()
        return {row['panorama_id']: self._state(row) for row in records}

    def _state(self, row):
        downloaded, total = 0, 0
        identifier = row['external_id']
        if isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
            try:
                downloaded, total = self._count(self.root / identifier)
            except (OSError, ValueError, KeyError, TypeError, StopIteration, ZeroDivisionError):
                pass
        return DownloadState(row['status'], downloaded, total, row['error_message'] or '')

    @staticmethod
    def _count(directory):
        payload = json.loads((directory / 'metadata.json').read_text())
        images = payload.get('rawResponse', payload)['data']['Data']['Images']
        zoom = next(item for item in images['Zooms'] if item['level'] == 0)
        columns, rows = (math.ceil(zoom[key] / images['Tiles'][key]) for key in ('width', 'height'))
        files = {path.name for path in (directory / '0').glob('tile_*_*.jpg') if path.is_file()}
        count = sum(f'tile_{column}_{row}.jpg' in files for column in range(columns) for row in range(rows))
        return count, columns * rows
