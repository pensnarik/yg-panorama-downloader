#!/usr/bin/env python3
"""Find pending archive images and invoke download commands safely."""
from pathlib import Path
import subprocess
import sys
import time
import psycopg
from psycopg.rows import dict_row
from .merge import ArchiveDatabase
from .metadata import MetadataExporter


class DownloadMonitor:
    PROVIDERS = {'google': ('pano-google.py', 5), 'yandex': ('pano.py', 0)}

    def download(self, panorama_id, provider):
        if provider not in self.PROVIDERS:
            print(f'Unknown provider {provider}', flush=True)
            return
        script, level = self.PROVIDERS[provider]
        if provider == 'yandex':
            MetadataExporter().sync([panorama_id])
        self._execute(script, panorama_id, level)
        self._merge(panorama_id, provider, level)

    def _merge(self, panorama_id, provider, level):
        print(f'{panorama_id}: склейка панорамы…', flush=True)
        self._execute('merge.py', panorama_id, level, '--provider', provider)
        print(f'{panorama_id}: готово', flush=True)

    @staticmethod
    def _execute(script, *arguments):
        path = Path(__file__).resolve().parents[1] / script
        subprocess.run([sys.executable, str(path), *map(str, arguments)], check=True)

    @staticmethod
    def _records():
        with psycopg.connect(**ArchiveDatabase.SETTINGS) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute('select external_id, provider from aa.panorama order by first_seen_at, external_id')
                return cursor.fetchall()

    def monitor(self):
        MetadataExporter().sync()
        for record in self._records():
            identifier, provider = record['external_id'], record['provider']
            if not (Path('panos') / f'{identifier}.jpg').exists():
                print(f'Starting to download {identifier}', flush=True)
                self.download(identifier, provider)
                return
        print('Новых панорам нет. Следующая проверка через 10 секунд.', flush=True)

    def run(self):
        print('Монитор скачивания запущен. Проверка каталога каждые 10 секунд.', flush=True)
        while True:
            try:
                self.monitor()
            except (subprocess.CalledProcessError, psycopg.Error) as error:
                print(f'Download failed: {error}', flush=True)
            time.sleep(10)
