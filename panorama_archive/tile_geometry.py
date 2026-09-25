#!/usr/bin/env python3
"""Use saved provider dimensions instead of guessing tile grid bounds."""
import json
import math
from pathlib import Path


class TileGeometry:
    @staticmethod
    def read(image_id, level):
        path = Path('map') / image_id / 'metadata.json'
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding='utf-8'))
        images = data.get('rawResponse', data)['data']['Data']['Images']
        zoom = next(item for item in images['Zooms'] if item['level'] == level)
        tile = images['Tiles']
        return math.ceil(zoom['width'] / tile['width']), math.ceil(zoom['height'] / tile['height'])

    @classmethod
    def verify(cls, image_id, level):
        columns, rows = cls.read(image_id, level)
        directory = Path('map') / image_id / str(level)
        if any(not (directory / f'tile_{column}_{row}.jpg').is_file()
               for column in range(columns) for row in range(rows)):
            raise ValueError('Не все тайлы панорамы скачаны')
