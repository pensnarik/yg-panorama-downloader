#!/usr/bin/env python3
"""Provider-aware tile download with resumable local files."""
import argparse
from pathlib import Path
from urllib.parse import quote
from .http import RateLimitedHttp


class TileProvider:
    RANGES = {'yandex': {0: (74, 29), 1: (28, 14)}, 'google': {4: (10, 10), 5: (26, 13)}}

    def __init__(self, name, image_id, level):
        self.name, self.image_id, self.level = name, image_id, level
        self.columns, self.rows = self.RANGES[name][level]
        self.boundary_status = 404 if name == 'yandex' else 400

    def url(self, column, row):
        identifier = quote(self.image_id, safe='')
        if self.name == 'yandex':
            return f'https://pano.maps.yandex.net/{identifier}/{self.level}.{column}.{row}'
        return ('https://streetviewpixels-pa.googleapis.com/v1/tile?'
                f'cb_client=maps_sv.tactile&panoid={identifier}&x={column}&y={row}'
                f'&zoom={self.level}&nbt=1&fover=2')


class TileDownloader:
    def __init__(self, provider, root=Path('map'), interval=.5):
        self.provider = provider
        self.directory = root / provider.image_id / str(provider.level)
        self.http = RateLimitedHttp(interval)

    def run(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        print(f'Downloading {self.provider.image_id}')
        for column in range(self.provider.columns):
            if not self._download_column(column):
                break

    def _download_column(self, column):
        for row in range(self.provider.rows):
            if self._download_tile(column, row) == self.provider.boundary_status:
                return row != 0
        return True

    def _download_tile(self, column, row):
        target = self.directory / f'tile_{column}_{row}.jpg'
        if target.exists():
            return 200
        response = self.http.get(self.provider.url(column, row))
        if response.status_code == 200:
            self._save(target, response.content)
        elif response.status_code != self.provider.boundary_status:
            raise RuntimeError(f'Could not download {response.url}: HTTP {response.status_code}')
        return response.status_code

    @staticmethod
    def _save(target, content):
        temporary = target.with_suffix('.jpg.part')
        temporary.write_bytes(content)
        temporary.replace(target)


class DownloadCommand:
    @classmethod
    def run(cls, provider_name, arguments=None):
        options = cls._parse(provider_name, arguments)
        provider = TileProvider(provider_name, options.image_id, options.level)
        TileDownloader(provider, interval=options.request_interval).run()
        return 0

    @staticmethod
    def _parse(provider_name, arguments):
        parser = argparse.ArgumentParser(description='Download panorama tiles')
        parser.add_argument('image_id')
        parser.add_argument('level', type=int, choices=TileProvider.RANGES[provider_name])
        parser.add_argument('--request-interval', type=DownloadCommand._interval, default=.5,
                            help='Pause between HTTP requests in seconds (default: 0.5)')
        options = parser.parse_args(arguments)
        if Path(options.image_id).name != options.image_id or options.image_id in ('.', '..'):
            parser.error('image_id must be a single directory name')
        return options

    @staticmethod
    def _interval(value):
        try:
            return RateLimitedHttp(float(value)).interval
        except ValueError as error:
            raise argparse.ArgumentTypeError(str(error)) from error
