#!/usr/bin/env python3
"""Find pending archive images and invoke download commands safely."""
from pathlib import Path
import subprocess
import sys
import time
import re
import psycopg
from psycopg.rows import dict_row
from .merge import ArchiveDatabase
from .metadata import MetadataExporter

from .logging import DownloadLog
from .queue_worker import QueueWorker

class DownloadMonitor:
    PROVIDERS = {'google': ('pano-google.py', 5), 'yandex': ('pano.py', 0)}

    def download(self, panorama_id, provider):
        if provider not in self.PROVIDERS:
            DownloadLog.write(f'Unknown provider {provider}', flush=True)
            return
        script, level = self.PROVIDERS[provider]
        if provider == 'yandex':
            MetadataExporter().sync([panorama_id])
        self._execute(script, panorama_id, level)
        self._merge(panorama_id, provider, level)

    def _merge(self, panorama_id, provider, level):
        DownloadLog.write(f'{panorama_id}: склейка панорамы…', flush=True)
        self._execute('merge.py', panorama_id, level, '--provider', provider)
        DownloadLog.write(f'{panorama_id}: готово', flush=True)

    @staticmethod
    def _execute(script, *arguments):
        path = Path(__file__).resolve().parents[1] / script
        subprocess.run([sys.executable, str(path), *map(str, arguments)], check=True, stderr=subprocess.PIPE, text=True)

    @staticmethod
    def _records():
        with psycopg.connect(**ArchiveDatabase.SETTINGS) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("""select external_id, provider from aa.panorama p where not exists
                    (select 1 from aa.panorama_download_queue q where (q.external_id = p.external_id or q.panorama_id = p.panorama_id)
                     and p.provider = 'yandex' and q.status <> 'completed') order by first_seen_at, external_id""")
                return cursor.fetchall()

    def monitor(self):
        if QueueWorker(self).process():
            return
        self._catalog()

    def _catalog(self):
        MetadataExporter().sync()
        for record in self._records():
            identifier, provider = record['external_id'], record['provider']
            if not (Path('panos') / f'{identifier}.jpg').exists():
                DownloadLog.write(f'Starting to download {identifier}', flush=True)
                self.download(identifier, provider)
                return
        DownloadLog.write('Новых панорам нет. Следующая проверка через 10 секунд.', flush=True)

    @staticmethod
    def _report_failure(error):
        details = getattr(error, 'stderr', None) or ''
        match = re.search(r'^(?:RuntimeError: )?(\[поток \d+ \| прокси [^\]\r\n]+\] .+)$', details, re.MULTILINE)
        if match:
            print(match[1], flush=True)
        else:
            DownloadLog.write(f'Download failed: {error}')
            if details.strip():
                DownloadLog.write(details.strip().splitlines()[-1])

    def run(self):
        DownloadLog.write('Монитор скачивания запущен. Проверка очереди и каталога каждые 10 секунд.', flush=True)
        while True:
            try:
                self.monitor()
            except (subprocess.CalledProcessError, psycopg.Error) as error:
                self._report_failure(error)
            time.sleep(10)
