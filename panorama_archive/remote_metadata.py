#!/usr/bin/env python3
"""Resolve provider panorama IDs to complete geometry and tile image IDs."""
from datetime import datetime, timezone
from urllib.parse import urlencode
import psycopg
from .capture import CaptureNormalizer
from .catalog import PanoramaCatalog
from .http import RateLimitedHttp
from .merge import ArchiveDatabase
from .proxies import ProxyList


class RemoteMetadata:
    ENDPOINT = 'https://api-maps.yandex.ru/services/panoramas/1.x/'

    def fetch(self, identifier):
        url = self.ENDPOINT + '?' + urlencode(dict(oid=identifier, origin='userAction', provider='streetview', l='stv', lang='ru_RU'))
        proxies = ProxyList.read(None)
        http = RateLimitedHttp(proxy=proxies[0] if proxies else None)
        try:
            with http.get(url) as response:
                response.raise_for_status()
                return self._normalize(response.json(), identifier, url)
        finally:
            http.close()

    @staticmethod
    def _normalize(raw, identifier, url):
        data = RemoteMetadata._provider_data(raw)
        if data.get('panoramaId') != identifier:
            raise ValueError('API вернул метаданные другой панорамы')
        envelope = dict(schemaVersion=1, provider='yandex', panoramaId=identifier,
                        imageId=data.get('Images', {}).get('imageId'), rawResponse=raw,
                        capturedAt=datetime.now(timezone.utc).isoformat(), sourceUrl=url)
        return RemoteMetadata._geometry(CaptureNormalizer.normalize(envelope))

    @staticmethod
    def _provider_data(raw):
        try:
            data = raw['data']['Data']
            if not isinstance(data, dict) or not isinstance(data.get('Images'), dict):
                raise ValueError('Некорректные данные панорамы от API')
            return data
        except (KeyError, TypeError):
            raise ValueError('API не вернул данные панорамы') from None

    @staticmethod
    def _geometry(metadata):
        if not metadata['geometryFieldsPresent']:
            raise ValueError('API не вернул полную геометрию панорамы')
        return metadata

    @staticmethod
    def save(metadata):
        with psycopg.connect(**ArchiveDatabase.SETTINGS) as connection:
            with connection.cursor() as cursor:
                PanoramaCatalog.metadata(cursor, metadata)
        return metadata['imageId']
