#!/usr/bin/env python3
"""Export captured geometry alongside local tiles without contacting providers."""
import argparse
import json
from pathlib import Path
import re
import tempfile
import psycopg
from .merge import ArchiveDatabase
from .titles import CatalogTitles


class MetadataExporter:
    QUERY = '''select external_id, capture_envelope || jsonb_build_object('catalogTitle', title)
        from aa.panorama_payload join aa.panorama using (provider, external_id)
        where provider = 'yandex' and external_id = any(%s) and capture_envelope is not null'''

    def __init__(self, root=Path('map')):
        self.root = Path(root)

    def sync(self, image_ids=None):
        identifiers = self._missing(image_ids)
        if not identifiers:
            return 0
        with psycopg.connect(**ArchiveDatabase.SETTINGS) as connection:
            with connection.cursor() as cursor:
                cursor.execute(self.QUERY, [identifiers])
                records = cursor.fetchall()
        return sum(self._save(identifier, metadata) for identifier, metadata in records)

    def _missing(self, image_ids):
        if image_ids is None:
            image_ids = [path.name for path in self.root.glob('*') if path.is_dir()]
        return [identifier for identifier in image_ids if self._valid_id(identifier)
                and not (self.root / identifier / 'metadata.json').exists()]

    @staticmethod
    def _valid_id(identifier):
        return isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9_-]+', identifier) is not None

    def _save(self, identifier, metadata):
        self._validate(identifier, metadata)
        destination = self.root / identifier / 'metadata.json'
        if destination.exists():
            return self._update_title(destination, metadata)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._write(destination, metadata)
        print(f'Saved metadata: {destination}', flush=True)
        return 1

    def _update_title(self, destination, metadata):
        title = CatalogTitles.normalize(metadata.get('catalogTitle'))
        if not title:
            return 0
        existing = json.loads(destination.read_text(encoding='utf-8'))
        self._validate(destination.parent.name, existing)
        if existing.get('catalogTitle') == title:
            return 0
        self._write(destination, existing | {'catalogTitle': title})
        return 1

    @classmethod
    def _validate(cls, identifier, metadata):
        if not cls._valid_id(identifier):
            raise ValueError('Invalid metadata image ID')
        data = metadata.get('rawResponse', metadata).get('data', {}).get('Data', {})
        if data.get('Images', {}).get('imageId') != identifier:
            raise ValueError(f'Metadata does not match image {identifier}')

    @staticmethod
    def _write(destination, metadata):
        payload = json.dumps(metadata, ensure_ascii=False, indent=2) + '\n'
        with tempfile.TemporaryDirectory(prefix='.metadata-', dir=destination.parent) as directory:
            temporary = Path(directory) / 'metadata.json'
            temporary.write_text(payload, encoding='utf-8')
            temporary.replace(destination)


class MetadataCommand:
    @staticmethod
    def run():
        parser = argparse.ArgumentParser(description='Export missing local panorama metadata from PostgreSQL')
        parser.add_argument('--root', type=Path, default=Path('map'))
        options = parser.parse_args()
        count = MetadataExporter(options.root).sync()
        print(f'Exported {count} metadata files')


if __name__ == '__main__':
    MetadataCommand.run()
