#!/usr/bin/env python3
"""Catalog updates participate in the caller's transaction with the original logs."""
import hashlib
import json
from psycopg.types.json import Jsonb
from .records import PanoramaRecord
from .titles import CatalogTitles


class CatalogQueries:
    DATE_FIELDS = ('shooting_year', 'shooting_month', 'shooting_day', 'date_precision', 'date_source',
                   'date_conflict', 'time_candidate', 'time_source')
    HAS_METADATA = ('exists (select 1 from aa.panorama_payload payload where payload.provider = aa.panorama.provider '
                    'and payload.external_id = aa.panorama.external_id and payload.capture_envelope is not null)')
    RANK = "case {table}.date_precision when 'day' then 3 when 'month' then 2 when 'year' then 1 else 0 end"
    COLUMNS = ('provider external_id panorama_id title latitude longitude altitude shooting_year shooting_month '
               'shooting_day date_precision date_source date_conflict time_candidate time_source provider_timestamp '
               'origin_azimuth origin_tilt tile_width tile_height view_azimuth view_pitch span_horizontal span_vertical '
               'geometry_valid source_url client_observed_at received_at')
    OBSERVATION = ('provider external_id panorama_id title latitude longitude shooting_year shooting_month shooting_day '
                   'date_precision date_source date_conflict time_candidate time_source page_date legacy_timestamp')
    CAPTURE = '''insert into aa.panorama_capture (provider, external_id, response_hash, metadata)
        values ('yandex', %s, %s, %s) on conflict (provider, external_id, response_hash)
        do update set last_received_at = now()'''
    LEVEL = '''insert into aa.panorama_level (provider, external_id, level, width, height, details)
        values ('yandex', %s, %s, %s, %s, %s) on conflict (provider, external_id, level)
        do update set width = excluded.width, height = excluded.height, details = excluded.details'''

    @classmethod
    def upsert(cls, strong):
        columns = (cls.COLUMNS if strong else cls.OBSERVATION).split()
        updates = [cls._assignment(name, strong) for name in columns if name not in ('provider', 'external_id')]
        names = ', '.join(columns)
        return (f'insert into aa.panorama ({names}) select {names} from jsonb_populate_record(null::aa.panorama, %s) '
                'on conflict (provider, external_id) do update set ' + ', '.join(updates) + ', last_seen_at = now()')

    @staticmethod
    def _assignment(name, strong):
        if name == 'title':
            return CatalogTitles.assignment(strong, CatalogQueries.HAS_METADATA)
        return CatalogQueries._field_assignment(name, strong)

    @staticmethod
    def _field_assignment(name, strong):
        if strong:
            return f'{name} = excluded.{name}'
        if name in ('page_date', 'legacy_timestamp'):
            return f'{name} = coalesce(excluded.{name}, aa.panorama.{name})'
        preserve = CatalogQueries.HAS_METADATA
        if name in CatalogQueries.DATE_FIELDS:
            preserve += ' or (' + CatalogQueries.RANK.format(table='aa.panorama') + ') > (' + CatalogQueries.RANK.format(table='excluded') + ')'
        return (f'{name} = case when {preserve} then aa.panorama.{name} '
                f'else coalesce(excluded.{name}, aa.panorama.{name}) end')


class PayloadQueries:
    @staticmethod
    def upsert(strong):
        fields = 'projection images default_view annotation raw_response capture_envelope' if strong else 'latest_observation'
        columns = 'provider, external_id, ' + ', '.join(fields.split())
        updates = ', '.join(f'{name} = excluded.{name}' for name in fields.split())
        return (f'insert into aa.panorama_payload ({columns}) select {columns} '
                'from jsonb_populate_record(null::aa.panorama_payload, %s) '
                f'on conflict (provider, external_id) do update set {updates}')


class PanoramaCatalog:
    @classmethod
    def metadata(cls, cursor, metadata):
        record = PanoramaRecord(metadata)
        fields = record.fields()
        cursor.execute(CatalogQueries.upsert(True), [Jsonb(fields)])
        cursor.execute(PayloadQueries.upsert(True), [Jsonb(fields)])
        cls._capture(cursor, fields['external_id'], metadata, record.raw)
        cls._levels(cursor, fields['external_id'], record.images.get('Zooms', []))

    @staticmethod
    def observation(cursor, provider, data):
        fields = Jsonb(PanoramaRecord.observation(provider, data))
        cursor.execute(CatalogQueries.upsert(False), [fields])
        cursor.execute(PayloadQueries.upsert(False), [fields])

    @staticmethod
    def _capture(cursor, image_id, metadata, raw):
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cursor.execute(CatalogQueries.CAPTURE, [image_id, digest, Jsonb(metadata)])

    @classmethod
    def _levels(cls, cursor, image_id, levels):
        cursor.execute("delete from aa.panorama_level where provider = 'yandex' and external_id = %s", [image_id])
        for level in levels if isinstance(levels, list) else []:
            if cls._valid_level(level):
                cursor.execute(CatalogQueries.LEVEL, [image_id, level['level'], level['width'], level['height'], Jsonb(level)])

    @staticmethod
    def _valid_level(level):
        return (isinstance(level, dict) and all(isinstance(level.get(name), int) and not isinstance(level[name], bool)
                for name in ('level', 'width', 'height')) and level['level'] >= 0 and level['width'] > 0 and level['height'] > 0)
