#!/usr/bin/env python3
"""Best-effort database recovery of metadata for locally downloaded panoramas."""
from pathlib import Path
import psycopg
from panorama_archive.merge import ArchiveDatabase
from panorama_archive.metadata import MetadataExporter


class LibraryDatabaseSync:
    QUERY = '''select external_id, capture_envelope || jsonb_build_object('catalogTitle', title)
        from aa.panorama_payload join aa.panorama using (provider, external_id)
        where provider = 'yandex' and capture_envelope is not null order by external_id'''

    def __init__(self, root):
        self.root = Path(root)
        self.exporter = MetadataExporter(self.root)

    def refresh(self):
        try:
            return sum(self._save(identifier, metadata) for identifier, metadata in self._records())
        except (psycopg.Error, OSError, ValueError, TypeError, KeyError, AttributeError):
            print('Каталог БД недоступен: используется локальная библиотека.', flush=True)
            return 0

    def _records(self):
        with psycopg.connect(**ArchiveDatabase.SETTINGS, connect_timeout=3,
                             options='-c statement_timeout=3000') as connection:
            with connection.cursor() as cursor:
                cursor.execute(self.QUERY)
                return cursor.fetchall()

    def _save(self, identifier, metadata):
        if not self.exporter._valid_id(identifier):
            return 0
        if not any((self.root / identifier).glob('*/tile_*_*.jpg')):
            return 0
        try:
            return self.exporter._save(identifier, metadata)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return 0
