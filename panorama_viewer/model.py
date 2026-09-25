#!/usr/bin/env python3
"""Local panorama metadata and archive selection."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from panorama_archive.dates import ShootingDate
from panorama_archive.titles import CatalogTitles
from .markers import PanoramaMarkers


class MetadataValues:
    @staticmethod
    def positive_integer(value):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError('Размеры изображения должны быть положительными целыми числами')
        return value

    @staticmethod
    def finite_pair(values):
        if len(values) != 2 or not all(math.isfinite(float(value)) for value in values):
            raise ValueError('Недопустимая пара углов')
        return tuple(map(float, values))

    @staticmethod
    def read(path):
        payload = json.loads(path.read_text())
        data = payload.get('rawResponse', payload).get('data', {}).get('Data')
        if not isinstance(data, dict):
            raise ValueError('В JSON нет rawResponse.data.Data или data.Data')
        return MetadataValues._catalog_title(payload, data)

    @staticmethod
    def _catalog_title(payload, data):
        title = CatalogTitles.normalize(payload.get('catalogTitle'))
        if not title:
            return data
        point = data.get('Point') or {}
        return data | {'Point': point | {'name': title}}


@dataclass(frozen=True)
class Level:
    number: int
    width: int
    height: int

    @classmethod
    def parse(cls, values):
        number = values['level']
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            raise ValueError('Недопустимый номер уровня')
        width = MetadataValues.positive_integer(values['width'])
        height = MetadataValues.positive_integer(values['height'])
        if height > width / 2 + 1:
            raise ValueError('Недопустимая высота сферической панорамы')
        return cls(number, width, height)

    def tile_count(self, tile_width, tile_height):
        return math.ceil(self.width / tile_width) * math.ceil(self.height / tile_height)


class TileCatalog:
    def __init__(self, panorama):
        self.panorama = panorama
        self.directory = self._find_directory()

    def _find_directory(self):
        parent, image_id = self.panorama.path.parent, self.panorama.image_id
        for directory in (parent, parent / image_id, parent / 'map' / image_id):
            if any((directory / str(level.number)).is_dir() for level in self.panorama.levels):
                return directory
        raise ValueError('Рядом с metadata.json не найдены каталоги уровней с тайлами')

    def _coordinates(self, level):
        for path in (self.directory / str(level.number)).glob('tile_*_*.jpg'):
            match = re.fullmatch(r'tile_(\d+)_(\d+)\.jpg', path.name)
            if match:
                column, row = map(int, match.groups())
                if self._inside(level, column, row):
                    yield column, row

    def _inside(self, level, column, row):
        return (column * self.panorama.tile_width < level.width
                and row * self.panorama.tile_height < level.height)

    def _candidate(self, level):
        found = set(self._coordinates(level))
        expected = level.tile_count(self.panorama.tile_width, self.panorama.tile_height)
        return len(found) == expected, level.width, level, found

    def select(self, requested_level):
        candidates = [self._candidate(level) for level in self.panorama.levels
                      if requested_level is None or level.number == requested_level]
        candidates = [candidate for candidate in candidates if candidate[3]]
        if not candidates:
            raise ValueError('Нет локальных тайлов для выбранного уровня')
        return max(candidates, key=self._rank)[2:]

    @staticmethod
    def _rank(candidate):
        return candidate[:2]


class Panorama:
    def __init__(self, source, level=None):
        self.path = self.metadata_path(source)
        self.data = MetadataValues.read(self.path)
        self._read_identity()
        self._read_dimensions()
        self._select_level(level)
        self._read_projection()
        self._read_view()
        self._read_annotations()

    def _read_annotations(self):
        self.shooting_date = ShootingDate.from_data(self.data)
        self.markers = PanoramaMarkers.read(self.path, self.data)

    @staticmethod
    def metadata_path(source):
        path = Path(source).expanduser().resolve()
        return path / 'metadata.json' if path.is_dir() else path

    def _read_identity(self):
        self.image_id = self.data['Images']['imageId']
        if not isinstance(self.image_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', self.image_id):
            raise ValueError('Недопустимый imageId')
        self.title = self.data.get('Point', {}).get('name') or self.image_id
        self.panorama_id = self.data.get('panoramaId')

    def _read_dimensions(self):
        images = self.data['Images']
        self.tile_width = MetadataValues.positive_integer(images['Tiles']['width'])
        self.tile_height = MetadataValues.positive_integer(images['Tiles']['height'])
        self.levels = [Level.parse(values) for values in images['Zooms']]
        if not self.levels:
            raise ValueError('Нет уровней сферической панорамы')

    def _select_level(self, requested_level):
        catalog = TileCatalog(self)
        self.directory = catalog.directory
        self.level, self.available_tiles = catalog.select(requested_level)
        self.expected_tiles = self.level.tile_count(self.tile_width, self.tile_height)

    def _read_projection(self):
        azimuth, horizon_tilt = MetadataValues.finite_pair(self.data['EquirectangularProjection']['Origin'])
        self.azimuth_origin = math.radians(azimuth)
        self.top = self._top_latitude(horizon_tilt)
        self.span = 2 * math.pi * self.level.height / self.level.width
        self.bottom = self.top - self.span

    def _top_latitude(self, horizon_tilt):
        lowest = min(self.levels, key=self._level_width)
        colatitude = math.pi / 2 - math.pi * lowest.height / lowest.width - math.radians(horizon_tilt)
        # Match Yandex's near-pole snap, based on the lowest-resolution level.
        return math.pi / 2 - (0 if colatitude < math.pi / 100 else colatitude)

    @staticmethod
    def _level_width(level):
        return level.width

    def _read_view(self):
        view = self.data.get('View', {})
        self.default_yaw, self.default_pitch = MetadataValues.finite_pair(view.get('Direction', [0, 0]))
        _, self.default_fov = MetadataValues.finite_pair(view.get('Span', [90, 60]))

    def tile_path(self, column, row):
        return self.directory / str(self.level.number) / f'tile_{column}_{row}.jpg'

    def read_region(self, x, y, width, height):
        from .tiles import RegionReader
        return RegionReader(self, x, y, width, height).read()


class PanoramaLibrary:
    @staticmethod
    def discover(root):
        return sorted(Path(root).glob('*/metadata.json'))

    @staticmethod
    def label(path):
        try:
            data = MetadataValues.read(path)
            return f"{data.get('Point', {}).get('name') or path.parent.name} · {data['Images']['imageId']}"
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return path.parent.name


from .atlas import AtlasLayout
from .tiles import MissingPattern

# Compatibility aliases keep existing callers working; implementations live in classes.
atlas_layout = AtlasLayout.calculate
missing_pattern = MissingPattern.create
discover = PanoramaLibrary.discover
