#!/usr/bin/env python3
"""Read image regions without stretching incomplete edge tiles."""
import math
import numpy as np
from PIL import Image


class MissingPattern:
    @staticmethod
    def create(width, height, x=0, y=0):
        rows, columns = np.ogrid[y:y + height, x:x + width]
        checks = ((columns // 32 + rows // 32) % 2).astype(np.uint8)
        return np.stack([27 + checks * 10, 34 + checks * 10, 42 + checks * 10], axis=-1)


class RegionReader:
    def __init__(self, panorama, x, y, width, height):
        self.panorama = panorama
        self.x, self.y = x, y
        self.right = min(x + width, panorama.level.width)
        self.bottom = min(y + height, panorama.level.height)
        self.image = Image.fromarray(MissingPattern.create(width, height, x, y))
        self.failures = set()

    def read(self):
        for column, row in self._intersecting_tiles():
            self._read_tile(column, row)
        return self.image, self.failures

    def _intersecting_tiles(self):
        tile_width, tile_height = self.panorama.tile_width, self.panorama.tile_height
        for row in range(self.y // tile_height, math.ceil(self.bottom / tile_height)):
            for column in range(self.x // tile_width, math.ceil(self.right / tile_width)):
                yield column, row

    def _read_tile(self, column, row):
        try:
            with Image.open(self.panorama.tile_path(column, row)) as source:
                tile = source.convert('RGB')
                self._check_size(tile, column, row)
                self._paste(tile, column, row)
        except (OSError, ValueError):
            self.failures.add((column, row))

    def _required_size(self, column, row):
        panorama = self.panorama
        return (min(panorama.tile_width, panorama.level.width - column * panorama.tile_width),
                min(panorama.tile_height, panorama.level.height - row * panorama.tile_height))

    def _check_size(self, tile, column, row):
        width, height = self._required_size(column, row)
        if tile.width < width or tile.height < height:
            self.failures.add((column, row))

    def _intersection(self, tile, column, row):
        origin_x = column * self.panorama.tile_width
        origin_y = row * self.panorama.tile_height
        required_width, required_height = self._required_size(column, row)
        return (max(self.x, origin_x), max(self.y, origin_y),
                min(self.right, origin_x + min(tile.width, required_width)),
                min(self.bottom, origin_y + min(tile.height, required_height)))

    def _paste(self, tile, column, row):
        left, top, right, bottom = self._intersection(tile, column, row)
        if right <= left or bottom <= top:
            return
        origin_x = column * self.panorama.tile_width
        origin_y = row * self.panorama.tile_height
        crop = tile.crop((left - origin_x, top - origin_y, right - origin_x, bottom - origin_y))
        self.image.paste(crop, (left - self.x, top - self.y))
