#!/usr/bin/env python3
"""Idempotent catalog population from logs, stored responses and offline archives."""
import argparse
import json
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from .catalog import PanoramaCatalog
from .merge import ArchiveDatabase


class CatalogBackfill:
    LOGS = '''select l.*, m.meta from aa.panorama_log l left join aa.panorama_log_meta m using (id) order by l.id'''
    HISTORY = '''update aa.panorama p set first_seen_at = l.first_seen, last_seen_at = greatest(p.last_seen_at,l.last_seen)
        from (select provider, external_id, min(created_at) first_seen, max(created_at) last_seen
              from aa.panorama_log group by provider, external_id) l
        where p.provider = l.provider and p.external_id = l.external_id'''

    def __init__(self, library=Path('map')):
        self.library = Path(library)

    def run(self):
        with psycopg.connect(**ArchiveDatabase.SETTINGS) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                self._logs(cursor)
                self._local(cursor)
                self._metadata(cursor)
                cursor.execute(self.HISTORY)
                cursor.execute('select count(*) as count from aa.panorama')
                count = cursor.fetchone()['count']
        return count

    def _logs(self, cursor):
        cursor.execute(self.LOGS)
        for row in cursor.fetchall():
            PanoramaCatalog.observation(cursor, row['provider'], self._observation(row))

    @staticmethod
    def _observation(row):
        meta = row.get('meta') or {}
        point = f"{row['lon']},{row['lat']}" if row['lon'] is not None and row['lat'] is not None else None
        return {'panoramaId': row['external_id'], 'panoramaPoint': point,
                'panoramaIdFromURL': meta.get('panorama_id_from_url', meta.get('panarama_id_from_url')),
                'year': row['time_info'] or row['year'], 'view': row['view_name'], 'tileName': row['tile_name'],
                'legacyTimestamp': row['unix_timestamp'], 'legacyLogId': row['id']}

    @staticmethod
    def _metadata(cursor):
        cursor.execute('select metadata from aa.yandex_panorama_metadata order by updated_at')
        for row in cursor.fetchall():
            PanoramaCatalog.metadata(cursor, row['metadata'])

    def _local(self, cursor):
        for path in sorted(self.library.glob('*/metadata.json')):
            metadata = json.loads(path.read_text())
            raw = metadata.get('rawResponse', metadata)
            if raw.get('data', {}).get('Data', {}).get('Images', {}).get('imageId') == path.parent.name:
                PanoramaCatalog.metadata(cursor, metadata)


class BackfillCommand:
    @staticmethod
    def run():
        parser = argparse.ArgumentParser(description='Populate aa.panorama after migration V003')
        parser.add_argument('--library', type=Path, default=Path('map'))
        options = parser.parse_args()
        print(f'Panorama catalog: {CatalogBackfill(options.library).run()} records')


if __name__ == '__main__':
    BackfillCommand.run()
