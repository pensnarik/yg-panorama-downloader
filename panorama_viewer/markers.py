#!/usr/bin/env python3
"""Offline geographic annotations projected into the viewer's east/up/north frame."""
from dataclasses import dataclass
import json
import math
import numpy as np
from .projection import SphericalProjection


@dataclass(frozen=True)
class PanoramaMarker:
    name: str
    description: str
    direction: np.ndarray
    distance: float


class MarkerGeometry:
    @staticmethod
    def coordinates(values):
        longitude, latitude = map(float, values[:2])
        altitude = float(values[2]) if len(values) > 2 else 0
        if not all(math.isfinite(value) for value in (longitude, latitude, altitude)):
            raise ValueError('Invalid marker coordinates')
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError('Invalid marker location')
        return math.radians(longitude), math.radians(latitude), altitude

    @classmethod
    def direction(cls, origin, position):
        longitude, latitude, altitude = cls.coordinates(origin)
        target_lon, target_lat, target_alt = cls.coordinates(position)
        delta = target_lon - longitude
        east = math.cos(target_lat) * math.sin(delta)
        north = math.cos(latitude) * math.sin(target_lat) - math.sin(latitude) * math.cos(target_lat) * math.cos(delta)
        vector = np.array([6378137 * east, target_alt - altitude, 6378137 * north])
        return cls._normalize(vector)

    @staticmethod
    def _normalize(vector):
        distance = float(np.linalg.norm(vector))
        if distance < .01:
            raise ValueError('Marker coincides with camera')
        return vector / distance, distance

    @staticmethod
    def screen(marker, camera, width, height):
        right, up, forward = SphericalProjection.camera_basis(camera.yaw, camera.pitch)
        depth = float(marker.direction @ forward)
        if depth <= 0 or width <= 0 or height <= 0:
            return None
        focal = height / (2 * math.tan(math.radians(camera.fov) / 2))
        horizontal = width / 2 + focal * float(marker.direction @ right) / depth
        vertical = height / 2 - focal * float(marker.direction @ up) / depth
        return (horizontal, vertical) if 0 <= horizontal < width and 0 <= vertical < height else None


class PanoramaMarkers:
    @classmethod
    def read(cls, path, data):
        payload = json.loads(path.read_text())
        annotation = payload.get('rawResponse', payload).get('data', {}).get('Annotation') or {}
        features = annotation.get('Markers', []) if isinstance(annotation, dict) else []
        origin = (data.get('Point') or {}).get('coordinates', [])
        markers = [cls._parse(feature, origin) for feature in features] if isinstance(features, list) else []
        return sorted((marker for marker in markers if marker is not None), key=lambda marker: marker.distance)

    @staticmethod
    def _parse(feature, origin):
        try:
            geometry, properties = feature['geometry'], feature['properties']
            name = properties.get('name') or properties.get('description')
            if geometry.get('type') != 'Point' or not isinstance(name, str) or not name.strip():
                return None
            direction, distance = MarkerGeometry.direction(origin, geometry['coordinates'])
            return PanoramaMarker(name.strip(), str(properties.get('description') or name), direction, distance)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            return None


class MarkerPlacement:
    @staticmethod
    def rectangle(center, size, viewport, occupied):
        horizontal, vertical = center
        width, height = size
        rectangle = (horizontal - width / 2, vertical - height / 2, width, height)
        left, top = rectangle[:2]
        if left < 0 or top < 0 or left + width > viewport[0] or top + height > viewport[1]:
            return None
        return None if any(MarkerPlacement.overlaps(rectangle, previous) for previous in occupied) else rectangle

    @staticmethod
    def overlaps(first, second):
        left, top, width, height = first
        other_left, other_top, other_width, other_height = second
        return (left < other_left + other_width + 6 and left + width + 6 > other_left
                and top < other_top + other_height + 6 and top + height + 6 > other_top)
