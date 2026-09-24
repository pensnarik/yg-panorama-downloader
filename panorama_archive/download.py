#!/usr/bin/env python3
"""Provider-aware tile download with resumable local files."""
import argparse
from pathlib import Path
from urllib.parse import quote
from threading import Lock
from .proxies import ProxyList
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


class DownloadProgress:
    def __init__(self, provider):
        self.provider = provider
        self.downloaded = self.cached = 0
        self.lock = Lock()

    def tile(self, column, row, status, cached):
        with self.lock:
            self._report(column, row, status, cached)

    def _report(self, column, row, status, cached):
        self.cached += int(status == 200 and cached)
        self.downloaded += int(status == 200 and not cached)
        outcome = 'уже на диске' if cached else 'сохранён' if status == 200 else f'граница HTTP {status}'
        print(f'{self.provider.image_id}: столбец {column + 1}/{self.provider.columns}, '
              f'тайл ({column}, {row}) — {outcome}; '
              f'скачано {self.downloaded}, пропущено {self.cached}', flush=True)

    def finish(self):
        print(f'{self.provider.image_id}: скачивание завершено; скачано {self.downloaded}, '
              f'уже на диске {self.cached}', flush=True)


class TileDownloader:
    def __init__(self, provider, root=Path('map'), interval=.5, proxies=None):
        self.provider = provider
        self.proxies, self.interval = proxies or [], interval
        self.directory = root / provider.image_id / str(provider.level)
        self.http = RateLimitedHttp(interval)
        self.progress = DownloadProgress(provider)

    def run(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        print(f'Downloading {self.provider.image_id}', flush=True)
        self._download_all()
        self.progress.finish()

    def _download_all(self):
        if self.proxies:
            from .parallel import ProxyDownloadPool
            return ProxyDownloadPool(self, self.proxies, self.interval).run()
        for column in range(self.provider.columns):
            if not self._download_column(column):
                break

    def _download_column(self, column):
        for row in range(self.provider.rows):
            cached = (self.directory / f'tile_{column}_{row}.jpg').exists()
            status = self._download_tile(column, row)
            self.progress.tile(column, row, status, cached)
            if status == self.provider.boundary_status:
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
        TileDownloader(provider, interval=options.request_interval, proxies=ProxyList.read(options.proxies_file)).run()
        return 0

    @staticmethod
    def _parse(provider_name, arguments):
        parser = argparse.ArgumentParser(description='Download panorama tiles')
        parser.add_argument('image_id')
        parser.add_argument('level', type=int, choices=TileProvider.RANGES[provider_name])
        parser.add_argument('--request-interval', type=DownloadCommand._interval, default=.5,
                            help='Pause between HTTP requests in seconds (default: 0.5)')
        parser.add_argument('--proxies-file', help='SOCKS proxy list (default: proxies.txt when present)')
        return DownloadCommand._options(parser, arguments)

    @staticmethod
    def _options(parser, arguments):
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
