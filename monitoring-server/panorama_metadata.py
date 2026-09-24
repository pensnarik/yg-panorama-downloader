#!/usr/bin/env python3
"""Validation and lossless normalization of provider metadata."""
from datetime import datetime, timezone
import math
import re
from urllib.parse import urlsplit


class GeometryValidator:
    @staticmethod
    def positive_integer(value):
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    @staticmethod
    def origin(values):
        return (isinstance(values, list) and len(values) == 2 and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            for value in values))

    @classmethod
    def dimensions(cls, values):
        return isinstance(values, dict) and all(cls.positive_integer(values.get(key)) for key in ('width', 'height'))

    @classmethod
    def zoom(cls, values):
        return (cls.dimensions(values) and isinstance(values.get('level'), int)
                and not isinstance(values['level'], bool) and values['level'] >= 0)

    @classmethod
    def missing(cls, data):
        projection, images = data.get('EquirectangularProjection'), data['Images']
        origin = projection.get('Origin') if isinstance(projection, dict) else None
        zooms = images.get('Zooms')
        checks = [('EquirectangularProjection.Origin', cls.origin(origin)),
                  ('Images.Tiles', cls.dimensions(images.get('Tiles'))),
                  ('Images.Zooms', isinstance(zooms, list) and bool(zooms) and all(map(cls.zoom, zooms)))]
        return [name for name, valid in checks if not valid]


class CaptureNormalizer:
    def __init__(self, capture):
        self.capture = capture
        self._validate_envelope()
        self.raw = capture['rawResponse']
        self.data = self.raw['data']['Data']
        self.images = self.data['Images']
        self._validate_identity()
        self._read_provenance()

    @classmethod
    def normalize(cls, capture):
        try:
            return cls(capture).build()
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError('Incomplete metadata envelope') from error

    def _validate_envelope(self):
        capture = self.capture
        if not isinstance(capture, dict) or capture.get('schemaVersion') != 1:
            raise ValueError('Expected metadata schemaVersion 1')
        if capture.get('provider') != 'yandex':
            raise ValueError('Expected provider yandex')
        raw = capture.get('rawResponse')
        if not isinstance(raw, dict) or raw.get('status') != 'success':
            raise ValueError('Expected a successful Yandex response')

    def _validate_identity(self):
        self.image_id, self.panorama_id = self.images['imageId'], self.data['panoramaId']
        if not isinstance(self.image_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', self.image_id):
            raise ValueError('Invalid imageId')
        if not isinstance(self.panorama_id, str) or not self.panorama_id:
            raise ValueError('Missing panoramaId')
        if self.capture.get('imageId') != self.image_id or self.capture.get('panoramaId') != self.panorama_id:
            raise ValueError('Capture IDs do not match the provider response')

    def _read_provenance(self):
        self.captured_at = datetime.fromisoformat(self.capture['capturedAt'].replace('Z', '+00:00'))
        if self.captured_at.tzinfo is None:
            raise ValueError('capturedAt must include a timezone')
        source = urlsplit(self.capture['sourceUrl'])
        if (source.scheme != 'https' or source.hostname != 'api-maps.yandex.ru'
                or not source.path.startswith('/services/panoramas/')):
            raise ValueError('Unexpected metadata source URL')

    def build(self):
        return self._identity_fields() | self._geometry_fields() | self._view_fields()

    def _identity_fields(self):
        return {'schemaVersion': 1, 'provider': 'yandex', 'imageId': self.image_id,
                'panoramaId': self.panorama_id, 'capturedAt': self.captured_at.isoformat(),
                'observedAt': self.captured_at.isoformat(), 'receivedAt': datetime.now(timezone.utc).isoformat(),
                'sourceUrl': self.capture['sourceUrl'], 'rawResponse': self.raw}

    def _geometry_fields(self):
        missing = GeometryValidator.missing(self.data)
        return {'geometryFieldsPresent': not missing, 'missingFields': missing,
                'projection': self.data.get('EquirectangularProjection'), 'images': self.images,
                'tileUrlTemplate': f'https://pano.maps.yandex.net/{self.image_id}/{{level}}.{{x}}.{{y}}',
                'localTileTemplate': f'map/{self.image_id}/{{level}}/tile_{{x}}_{{y}}.jpg'}

    def _view_fields(self):
        return {'position': self.data.get('Point'), 'timestamp': self.data.get('timestamp'),
                'defaultView': self.data.get('View')}


normalize_capture = CaptureNormalizer.normalize
