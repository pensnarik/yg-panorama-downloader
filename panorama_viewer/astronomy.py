#!/usr/bin/env python3
"""Offline topocentric ephemerides in the viewer's east/up/north frame."""
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import numpy as np
import ephem


@dataclass(frozen=True)
class ObserverLocation:
    longitude: float
    latitude: float
    elevation: float = 0

    def __post_init__(self):
        if not all(math.isfinite(value) for value in (self.longitude, self.latitude, self.elevation)):
            raise ValueError('Координаты наблюдателя должны быть конечными числами')
        if not -180 <= self.longitude <= 180 or not -90 <= self.latitude <= 90:
            raise ValueError('Координаты наблюдателя вне допустимого диапазона')

    @classmethod
    def from_panorama(cls, panorama):
        coordinates = panorama.data.get('Point', {}).get('coordinates', [])
        if not isinstance(coordinates, (tuple, list)) or len(coordinates) < 2:
            raise ValueError('В метаданных панорамы нет координат места съёмки')
        longitude, latitude = map(float, coordinates[:2])
        return cls(longitude, latitude)


@dataclass(frozen=True)
class CelestialBody:
    AU_KM = 149597870.7
    azimuth: float
    altitude: float
    radius: float
    distance: float

    @property
    def direction(self):
        cosine = math.cos(self.altitude)
        return np.array([math.sin(self.azimuth) * cosine, math.sin(self.altitude), math.cos(self.azimuth) * cosine])

    @classmethod
    def from_ephem(cls, body, radius_km):
        distance = float(body.earth_distance)
        radius = math.asin(radius_km / (distance * cls.AU_KM))
        return cls(float(body.az), float(body.alt), radius, distance)

    def description(self, name):
        return (f'{name}: азимут {math.degrees(self.azimuth):.1f}°, высота {math.degrees(self.altitude):+.1f}°'
                f', диаметр {math.degrees(self.radius) * 120:.1f}′')


@dataclass(frozen=True)
class SkySnapshot:
    timestamp: datetime
    sun: CelestialBody
    moon: CelestialBody

    @property
    def moon_light(self):
        light = self.sun.direction * self.sun.distance - self.moon.direction * self.moon.distance
        return light / np.linalg.norm(light)

    @property
    def moon_fraction(self):
        return float(np.clip((1 - np.dot(self.moon.direction, self.moon_light)) / 2, 0, 1))


@dataclass(frozen=True)
class SkyOverlay:
    snapshot: SkySnapshot
    sun_enabled: bool = False
    moon_enabled: bool = False

    @property
    def enabled(self):
        return self.sun_enabled or self.moon_enabled


class Ephemeris:
    @classmethod
    def calculate(cls, location, timestamp=None):
        timestamp = timestamp if timestamp is not None else datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError('Время расчёта должно содержать часовой пояс')
        timestamp = timestamp.astimezone(timezone.utc)
        observer = cls._observer(location, timestamp)
        return SkySnapshot(timestamp, CelestialBody.from_ephem(ephem.Sun(observer), 695700),
                           CelestialBody.from_ephem(ephem.Moon(observer), 1737.4))

    @staticmethod
    def _observer(location, timestamp):
        observer = ephem.Observer()
        observer.lon, observer.lat = math.radians(location.longitude), math.radians(location.latitude)
        observer.elevation = location.elevation
        observer.pressure = 0
        observer.date = timestamp.replace(tzinfo=None)
        return observer


class CelestialGeometry:
    @staticmethod
    def surface(rays, body):
        center = body.direction
        radial = math.sin(body.radius)
        perpendicular = np.linalg.norm(np.cross(rays, center), axis=-1)
        forward = rays @ center
        depth = np.sqrt(np.maximum(0, radial * radial - perpendicular * perpendicular))
        normal = (rays * (forward - depth)[..., None] - center) / radial
        return normal, (forward > 0) & (perpendicular <= radial)

    @staticmethod
    def projected_diameter(body, height, vertical_fov):
        return height * math.tan(body.radius) / math.tan(math.radians(vertical_fov) / 2)
