"""Read exported metadata and original tiles, preserving crop and pixel scale."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Level:
    number: int
    width: int
    height: int


class Panorama:
    def __init__(self, source, level=None):
        source = Path(source).expanduser().resolve()
        self.path = source / 'metadata.json' if source.is_dir() else source
        payload = json.loads(self.path.read_text())
        data = payload.get('rawResponse', payload).get('data', {}).get('Data')
        if not isinstance(data, dict):
            raise ValueError('В JSON нет rawResponse.data.Data или data.Data')
        self.data = data
        self.image_id = data['Images']['imageId']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', self.image_id):
            raise ValueError('Недопустимый imageId')
        self.title = data.get('Point', {}).get('name') or self.image_id
        self.panorama_id = data.get('panoramaId')
        self.tile_width = self._positive(data['Images']['Tiles']['width'])
        self.tile_height = self._positive(data['Images']['Tiles']['height'])
        self.levels = [Level(int(z['level']), self._positive(z['width']), self._positive(z['height']))
                       for z in data['Images']['Zooms']]
        if not self.levels or any(z.number < 0 or z.height > z.width / 2 + 1 for z in self.levels):
            raise ValueError('Недопустимые уровни сферической панорамы')
        # Resolve only local directories. Never follow remote templates in JSON.
        candidates = [self.path.parent, self.path.parent / self.image_id,
                      self.path.parent / 'map' / self.image_id]
        self.directory = next((p for p in candidates if any((p / str(z.number)).is_dir()
                                                             for z in self.levels)), None)
        if self.directory is None:
            raise ValueError('Рядом с metadata.json не найдены каталоги уровней с тайлами')
        available = []
        for z in self.levels:
            found = set()
            for p in (self.directory / str(z.number)).glob('tile_*_*.jpg'):
                match = re.fullmatch(r'tile_(\d+)_(\d+)\.jpg', p.name)
                if match:
                    x, y = map(int, match.groups())
                    if x * self.tile_width < z.width and y * self.tile_height < z.height:
                        found.add((x, y))
            if found:
                count = math.ceil(z.width / self.tile_width) * math.ceil(z.height / self.tile_height)
                available.append((len(found) == count, z.width, z, found))
        if level is not None:
            available = [a for a in available if a[2].number == level]
        if not available:
            raise ValueError('Нет локальных тайлов для выбранного уровня')
        _, _, self.level, self.available_tiles = max(available, key=lambda a: (a[0], a[1]))
        self.expected_tiles = math.ceil(self.level.width / self.tile_width) * math.ceil(self.level.height / self.tile_height)
        origin = data['EquirectangularProjection']['Origin']
        if len(origin) != 2 or not all(math.isfinite(float(n)) for n in origin):
            raise ValueError('Недопустимый EquirectangularProjection.Origin')
        self.azimuth_origin = math.radians(float(origin[0]))
        # Verified against Yandex's Panorama constructor: use the lowest width
        # to place the upper edge and snap a near-pole edge within pi/100.
        lowest = min(self.levels, key=lambda z: z.width)
        colatitude = math.pi / 2 - math.pi * lowest.height / lowest.width - math.radians(float(origin[1]))
        if colatitude < math.pi / 100:
            colatitude = 0.0
        self.top = math.pi / 2 - colatitude
        self.span = 2 * math.pi * self.level.height / self.level.width
        self.bottom = self.top - self.span
        view = data.get('View', {})
        direction = view.get('Direction', [0, 0])
        span = view.get('Span', [90, 60])
        self.default_yaw = float(direction[0])
        self.default_pitch = float(direction[1])
        self.default_fov = float(span[1])
        if not all(math.isfinite(n) for n in (self.default_yaw, self.default_pitch, self.default_fov)):
            raise ValueError('Недопустимое направление камеры')

    @staticmethod
    def _positive(value):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError('Размеры изображения должны быть положительными целыми числами')
        return value

    def tile_path(self, x, y):
        return self.directory / str(self.level.number) / f'tile_{x}_{y}.jpg'

    def read_region(self, x, y, width, height):
        """Read one atlas page; crop partial edge tiles, never stretch them."""
        pixels = missing_pattern(width, height, x, y)
        image = Image.fromarray(pixels)
        failures = set()
        right, bottom = min(x + width, self.level.width), min(y + height, self.level.height)
        for ty in range(y // self.tile_height, math.ceil(bottom / self.tile_height)):
            for tx in range(x // self.tile_width, math.ceil(right / self.tile_width)):
                ox, oy = tx * self.tile_width, ty * self.tile_height
                try:
                    with Image.open(self.tile_path(tx, ty)) as tile:
                        tile = tile.convert('RGB')
                        required_w = min(self.tile_width, self.level.width - ox)
                        required_h = min(self.tile_height, self.level.height - oy)
                        if tile.width < required_w or tile.height < required_h:
                            failures.add((tx, ty))
                        left, top = max(x, ox), max(y, oy)
                        r = min(right, ox + tile.width, ox + required_w)
                        b = min(bottom, oy + tile.height, oy + required_h)
                        if r > left and b > top:
                            crop = tile.crop((left - ox, top - oy, r - ox, b - oy))
                            image.paste(crop, (left - x, top - y))
                except (OSError, ValueError):
                    failures.add((tx, ty))
        return image, failures


def missing_pattern(width, height, x=0, y=0):
    yy, xx = np.ogrid[y:y + height, x:x + width]
    mask = ((xx // 32 + yy // 32) % 2).astype(np.uint8)
    return np.stack([27 + mask * 10, 34 + mask * 10, 42 + mask * 10], axis=-1)


def discover(root):
    return sorted(Path(root).glob('*/metadata.json'))


def atlas_layout(width, height, memory_mib, max_size=1024, max_layers=2048):
    side = min(1024, max_size)
    scale = 1
    while True:
        w, h = math.ceil(width / scale), math.ceil(height / scale)
        cols, rows = math.ceil(w / side), math.ceil(h / side)
        # RGB8 may be padded to 4 bytes by the driver; budget conservatively.
        if cols * rows <= max_layers and cols * rows * side * side * 4 <= memory_mib * 1024**2:
            return side, scale, w, h, cols, rows
        if w == 1 and h == 1:
            raise ValueError('Недостаточный лимит памяти для текстуры')
        scale *= 2
