#!/usr/bin/env python3
"""GPU budget and atlas page geometry, independent of GTK/OpenGL."""
import math
from typing import NamedTuple


class AtlasLayout(NamedTuple):
    side: int
    scale: int
    width: int
    height: int
    columns: int
    rows: int

    @classmethod
    def calculate(cls, width, height, memory_mib, max_size=1024, max_layers=2048):
        cls._validate(width, height, memory_mib, max_size, max_layers)
        scale = 1
        while True:
            layout = cls._scaled(width, height, min(1024, max_size), scale)
            if layout.fits(memory_mib, max_layers):
                return layout
            if layout.width == 1 and layout.height == 1:
                raise ValueError('Недостаточный лимит памяти для текстуры')
            scale *= 2

    @staticmethod
    def _validate(*values):
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError('Размеры, память и лимиты текстуры должны быть положительными')

    @classmethod
    def _scaled(cls, width, height, side, scale):
        scaled_width, scaled_height = math.ceil(width / scale), math.ceil(height / scale)
        return cls(side, scale, scaled_width, scaled_height,
                   math.ceil(scaled_width / side), math.ceil(scaled_height / side))

    def fits(self, memory_mib, max_layers):
        pages = self.columns * self.rows
        return pages <= max_layers and pages * self.side**2 * 4 <= memory_mib * 1024**2

    def pages(self):
        for row in range(self.rows):
            for column in range(self.columns):
                yield column, row

    def output_size(self, column, row):
        return min(self.side, self.width-column*self.side), min(self.side, self.height-row*self.side)

    def source_region(self, source_width, source_height, column, row):
        output_width, output_height = self.output_size(column, row)
        left = round(column * self.side * source_width / self.width)
        top = round(row * self.side * source_height / self.height)
        right = round((column*self.side+output_width) * source_width / self.width)
        bottom = round((row*self.side+output_height) * source_height / self.height)
        return left, top, right-left, bottom-top
