#!/usr/bin/env python3
"""Flat archive export with a database caption."""
import argparse
from pathlib import Path
import re
import psycopg
from psycopg.rows import dict_row
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .dates import ShootingDate


class ArchiveDatabase:
    SETTINGS = dict(dbname='panoramas', user='allarchive', password='allarchive', host='localhost', port=5432)
    TITLE_QUERY = '''select *, latitude as lat, longitude as lon, title as view_name
        from aa.panorama where external_id = %s and provider = %s'''

    def title(self, image_id, provider):
        with psycopg.connect(**self.SETTINGS) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(self.TITLE_QUERY, [image_id, provider])
                row = cursor.fetchone()
        if row is None:
            raise ValueError(f'Could not find {image_id} in the DB')
        return self._format_title(row)

    @staticmethod
    def _format_title(row):
        date = ShootingDate.from_columns(row).label() if 'date_precision' in row else row['unix_timestamp'] or row['date']
        title = f"{date}, {row['lat']},{row['lon']}"
        return title + (f" | {row['view_name']}" if row['view_name'] else '')


class CaptionPainter:
    def __init__(self):
        font_path = Path(__file__).resolve().parents[1] / 'font.ttf'
        self.font = ImageFont.truetype(str(font_path), size=80)

    def paint(self, image, text):
        shadow = Image.new('RGBA', image.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).text((10, 11), text, font=self.font, fill='#000000')
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=2))
        image.paste(shadow, mask=shadow)
        ImageDraw.Draw(image).text((10, 10), text, font=self.font, fill='white')


class FlatTileMerger:
    def __init__(self, directory, tile_size):
        self.directory, self.tile_size = directory, tile_size
        self.coordinates = self._coordinates()

    def _coordinates(self):
        coordinates = set()
        for path in self.directory.glob('tile_*_*.jpg'):
            match = re.fullmatch(r'tile_(\d+)_(\d+)\.jpg', path.name)
            if match:
                coordinates.add(tuple(map(int, match.groups())))
        if not coordinates:
            raise ValueError(f'No tiles found in {self.directory}')
        return coordinates

    def merge(self):
        columns = max(column for column, _ in self.coordinates) + 1
        rows = max(row for _, row in self.coordinates) + 1
        image = Image.new('RGB', (columns*self.tile_size, rows*self.tile_size), 'green')
        for column, row in self.coordinates:
            self._paste(image, column, row)
        return image

    def _paste(self, image, column, row):
        with Image.open(self.directory / f'tile_{column}_{row}.jpg') as source:
            tile = source.convert('RGB')
            if tile.size != (self.tile_size, self.tile_size):
                tile = tile.resize((self.tile_size, self.tile_size), Image.Resampling.LANCZOS)
            image.paste(tile, (column*self.tile_size, row*self.tile_size))


class MergeApplication:
    def __init__(self, arguments=None):
        options = self._parse(arguments)
        self.image_id, self.level = options.image_id, options.level
        self.provider = options.provider or ('google' if len(self.image_id) > 12 else 'yandex')

    @staticmethod
    def _parse(arguments):
        parser = argparse.ArgumentParser(description='Merge panorama tiles into a flat JPEG')
        parser.add_argument('image_id')
        parser.add_argument('level', type=int)
        parser.add_argument('--provider', choices=['google', 'yandex'])
        return parser.parse_args(arguments)

    def run(self):
        directory = Path('map') / self.image_id / str(self.level)
        size = 512 if self.provider == 'google' else 256
        image = FlatTileMerger(directory, size).merge()
        CaptionPainter().paint(image, ArchiveDatabase().title(self.image_id, self.provider))
        target = Path('panos') / f'{self.image_id}.jpg'
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        print(f'Panorama saved into {target}')
