#!/usr/bin/env python3
"""Typed catalog fields extracted without losing the provider envelope."""
import math
from datetime import datetime, timezone
from .dates import DateEvidence, ShootingDate


class RecordValues:
    @staticmethod
    def mapping(value):
        return value if isinstance(value, dict) else {}

    @staticmethod
    def dimension(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    @staticmethod
    def number(value):
        try:
            return float(value) if value is not None and not isinstance(value, bool) and math.isfinite(float(value)) else None
        except (ValueError, TypeError):
            return None

    @classmethod
    def pair(cls, values, names):
        values = values if isinstance(values, (list, tuple)) and len(values) >= 2 else [None, None]
        return dict(zip(names, map(cls.number, values[:2])))

    @staticmethod
    def known(value):
        return None if value in (None, '', 'unknown') else value


class PanoramaRecord:
    def __init__(self, metadata):
        self.metadata = metadata
        self.raw = metadata.get('rawResponse', metadata)
        self.data = self.raw['data']['Data']
        self.images = self.data['Images']

    def fields(self):
        return (self._identity() | self._position() | self._geometry() | self._view()
                | ShootingDate.from_data(self.data).columns() | self._provenance())

    def _identity(self):
        return {'provider': 'yandex', 'external_id': self.images['imageId'],
                'panorama_id': self.data['panoramaId'], 'raw_response': self.raw,
                'capture_envelope': self.metadata, 'annotation': self.raw['data'].get('Annotation')}

    def _position(self):
        point = RecordValues.mapping(self.data.get('Point'))
        coordinates = point.get('coordinates') or []
        return RecordValues.pair(coordinates, ('longitude', 'latitude')) | {
            'altitude': RecordValues.number(coordinates[2]) if len(coordinates) > 2 else None,
            'title': point.get('name')}

    def _geometry(self):
        projection = RecordValues.mapping(self.data.get('EquirectangularProjection'))
        tiles = RecordValues.mapping(self.images.get('Tiles'))
        return RecordValues.pair(projection.get('Origin'), ('origin_azimuth', 'origin_tilt')) | {
            'projection': projection, 'images': self.images, 'tile_width': RecordValues.dimension(tiles.get('width')),
            'tile_height': RecordValues.dimension(tiles.get('height')), 'geometry_valid': self.metadata.get('geometryFieldsPresent')}

    def _view(self):
        view = RecordValues.mapping(self.data.get('View'))
        return (RecordValues.pair(view.get('Direction'), ('view_azimuth', 'view_pitch'))
                | RecordValues.pair(view.get('Span'), ('span_horizontal', 'span_vertical'))
                | {'default_view': view})

    def _provenance(self):
        return {'source_url': self.metadata.get('sourceUrl'),
                'received_at': datetime.now(timezone.utc).isoformat(),
                'client_observed_at': DateEvidence.observed_at(self.metadata.get('capturedAt'))}

    @staticmethod
    def observation(provider, data):
        coordinates = (data.get('panoramaPoint') or '').split(',')
        return RecordValues.pair(coordinates, ('longitude', 'latitude')) | {
            'provider': provider, 'external_id': data['panoramaId'], 'latest_observation': data,
            'panorama_id': data.get('panoramaIdFromURL'), 'page_date': RecordValues.known(data.get('year')),
            'title': RecordValues.known(data.get('view')), 'legacy_timestamp': data.get('legacyTimestamp')
        } | ShootingDate.from_observation(provider, data).columns()
