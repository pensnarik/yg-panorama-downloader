#!/usr/bin/env python3
"""Sinusoidal paper gores: lengths in millimetres, angles in radians."""
from dataclasses import dataclass
import math
import numpy as np
from PIL import Image
from .projection import TileSampler


@dataclass(frozen=True)
class GlobeSettings:
    diameter: float = 100
    gores: int = 24
    dpi: int = 300
    yaw: float = 0

    def __post_init__(self):
        if not math.isfinite(self.diameter) or not 20 <= self.diameter <= 150:
            raise ValueError('Диаметр шара: 20–150 мм')
        if not isinstance(self.gores, int) or not 12 <= self.gores <= 48:
            raise ValueError('Количество лепестков: целое число от 12 до 48')
        if not isinstance(self.dpi, int) or not 72 <= self.dpi <= 600:
            raise ValueError('Разрешение печати: 72–600 DPI')
        if not math.isfinite(self.yaw):
            raise ValueError('Азимут должен быть конечным числом')

    @property
    def radius(self):
        return self.diameter / 2

    @property
    def width(self):
        return math.pi * self.diameter / self.gores

    @property
    def height(self):
        return math.pi * self.radius

    @property
    def pixels(self):
        return (math.ceil(self.width * self.dpi / 25.4), math.ceil(self.height * self.dpi / 25.4))

    def center(self, index):
        return math.radians(self.yaw) + index * 2 * math.pi / self.gores


class GoreProjection:
    @staticmethod
    def half_width(settings, latitude):
        return settings.width / 2 * np.cos(latitude)

    @staticmethod
    def coordinates(settings, index, horizontal, latitude):
        cosine = np.maximum(np.cos(latitude), 1e-15)
        longitude = settings.center(index) + horizontal / (settings.radius * cosine)
        inside = np.abs(horizontal) <= GoreProjection.half_width(settings, latitude)
        return longitude, inside

    @staticmethod
    def source(panorama, longitude, latitude):
        horizontal = ((longitude - panorama.azimuth_origin) / (2 * math.pi)) % 1
        vertical = (panorama.top - latitude) / panorama.span
        return (horizontal * panorama.level.width - .5, vertical * panorama.level.height - .5,
                (vertical >= 0) & (vertical <= 1))


class GoreRenderer:
    UNKNOWN = (235, 235, 235)

    def __init__(self, panorama, settings):
        self.panorama = panorama
        self.settings = settings
        self.sampler = TileSampler(panorama)

    def render(self, index):
        width, height = self.settings.pixels
        image = Image.new('RGB', (width, height), 'white')
        for start in range(0, height, 64):
            image.paste(self._band(index, start, min(64, height - start)), (0, start))
        self.sampler.cache.clear()
        return image

    def _grid(self, start, count):
        width, height = self.settings.pixels
        rows, columns = np.mgrid[start:start + count, :width]
        horizontal = ((columns + .5) / width - .5) * self.settings.width
        latitude = math.pi / 2 - (rows + .5) / height * math.pi
        return horizontal, latitude

    def _band(self, index, start, count):
        horizontal, latitude = self._grid(start, count)
        longitude, inside = GoreProjection.coordinates(self.settings, index, horizontal, latitude)
        source_x, source_y, covered = GoreProjection.source(self.panorama, longitude, latitude)
        pixels = np.full((*inside.shape, 3), 255, dtype=np.uint8)
        pixels[inside & ~covered] = self.UNKNOWN
        selected = inside & covered
        pixels[selected] = np.clip(self.sampler.interpolate(source_x[selected], source_y[selected]), 0, 255)
        return Image.fromarray(pixels)


class GlobeLayout:
    MARGIN = 10
    GAP = 4
    BOTTOM = 25

    def __init__(self, settings):
        self.settings = settings
        self.page_size = (297, 210) if settings.height <= 162 else (210, 297)
        available = self.page_size[0] - 2 * self.MARGIN
        self.per_page = int((available + self.GAP) // (settings.width + self.GAP))
        self.pages = math.ceil(settings.gores / self.per_page)

    def indices(self, page):
        return range(page * self.per_page, min((page + 1) * self.per_page, self.settings.gores))

    def center(self, page, index):
        count = len(self.indices(page))
        group_width = count * self.settings.width + (count - 1) * self.GAP
        left = (self.page_size[0] - group_width) / 2
        return left + self.settings.width / 2 + (index - page * self.per_page) * (self.settings.width + self.GAP)
