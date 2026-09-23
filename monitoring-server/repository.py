#!/usr/bin/env python3
"""Atomic persistence for metadata and tile observations."""
import psycopg
from psycopg.types.json import Jsonb


class DatabaseSettings:
    VALUES = dict(dbname='panoramas', user='allarchive', password='allarchive', host='localhost', port=5432)


class Queries:
    UPSERT = '''insert into aa.yandex_panorama_metadata
        (image_id, panorama_id, captured_at, metadata) values (%s, %s, %s, %s)
        on conflict (image_id) do update set panorama_id = excluded.panorama_id,
        captured_at = excluded.captured_at, metadata = excluded.metadata, updated_at = now()
        where excluded.captured_at > aa.yandex_panorama_metadata.captured_at returning image_id'''
    METADATA_LOG = '''insert into aa.panorama_log
        (provider, external_id, lat, lon, unix_timestamp, view_name)
        values ('yandex', %s, %s, %s, %s, %s) returning id'''
    YANDEX_LOG = '''insert into aa.panorama_log
        (provider, external_id, lat, lon, unix_timestamp, year, view_name, tile_name)
        values (%s, %s, %s, %s, %s, %s, %s, %s) returning id'''
    GOOGLE_LOG = '''insert into aa.panorama_log
        (provider, external_id, lat, lon, time_info, view_name, tile_name)
        values (%s, %s, %s, %s, %s, %s, %s) returning id'''
    LOG_META = 'insert into aa.panorama_log_meta (id, meta) values (%s, %s)'
    GET = 'select metadata from aa.yandex_panorama_metadata where image_id = %s'


class TileObservation:
    def __init__(self, data, provider):
        self.data, self.provider = data, provider

    def _coordinates(self):
        point = self.data.get('panoramaPoint')
        longitude, latitude = point.split(',') if point else (None, None)
        return latitude, longitude

    def timestamp(self):
        identifier = self.data.get('panoramaIdFromURL') or ''
        suffix = identifier.split('_')[-1]
        return int(suffix) if suffix.isdigit() else None

    @staticmethod
    def known(value):
        return None if value == 'unknown' else value

    def values(self):
        data = self.data
        common = [self.provider, data['panoramaId'], *self._coordinates()]
        details = [self.known(data['year']), self.known(data['view']), data['tileName']]
        return common + ([self.timestamp()] if self.provider == 'yandex' else []) + details

    def metadata(self):
        identifier = self.data.get('panoramaIdFromURL')
        return {'panarama_id_from_url': identifier, 'panorama_id_from_url': identifier,
                'observed_view': {'direction': self.data.get('direction'), 'span': self.data.get('span')},
                'source': 'tile-request'}


class PanoramaRepository:
    def __init__(self, settings):
        self.settings = settings

    def save(self, metadata):
        with psycopg.connect(**self.settings) as connection:
            with connection.cursor() as cursor:
                values = [metadata['imageId'], metadata['panoramaId'], metadata['capturedAt'], Jsonb(metadata)]
                cursor.execute(Queries.UPSERT, values)
                if cursor.fetchone():
                    self._metadata_log(connection, cursor, metadata)

    def _metadata_log(self, connection, cursor, metadata):
        point = metadata.get('position') or {}
        coordinates = point.get('coordinates') or []
        longitude, latitude = coordinates[:2] if len(coordinates) >= 2 else (None, None)
        values = [metadata['imageId'], latitude, longitude, metadata['timestamp'], point.get('name')]
        cursor.execute(Queries.METADATA_LOG, values)
        log_id = cursor.fetchone()[0]
        self.save_log_meta(connection, log_id, Jsonb(self._log_reference(metadata)))

    @staticmethod
    def _log_reference(metadata):
        return {'metadata_image_id': metadata['imageId'], 'panorama_id_from_url': metadata['panoramaId'],
                'source': 'panorama-response'}

    @staticmethod
    def save_log_meta(connection, log_id, metadata):
        with connection.cursor() as cursor:
            cursor.execute(Queries.LOG_META, [log_id, metadata])
        return True

    def get(self, image_id):
        with psycopg.connect(**self.settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(Queries.GET, [image_id])
                row = cursor.fetchone()
        return row[0] if row else None

    def observe(self, observation):
        query = Queries.YANDEX_LOG if observation.provider == 'yandex' else Queries.GOOGLE_LOG
        with psycopg.connect(**self.settings) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, observation.values())
                if observation.provider == 'yandex':
                    self.save_log_meta(connection, cursor.fetchone()[0], Jsonb(observation.metadata()))
