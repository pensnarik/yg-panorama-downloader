#!/usr/bin/env python3
"""Explicit historical panorama links; no geographic guessing or network access."""
from dataclasses import dataclass
from panorama_archive.dates import DateEvidence
from .navigation import PanoramaConnections


@dataclass(frozen=True)
class HistoricalPanorama:
    identifier: str
    label: str


class PanoramaHistory:
    @classmethod
    def read(cls, panorama):
        items = PanoramaConnections._annotation(panorama).get('HistoricalPanoramas') or []
        links = [cls._parse(item) for item in items] if isinstance(items, list) else []
        unique = {link.identifier: link for link in links if link}
        return sorted(unique.values(), key=lambda link: (link.label, link.identifier))

    @staticmethod
    def _parse(item):
        try:
            connection = item['Connection']
            identifier = PanoramaConnections._identifier(connection)
            date = DateEvidence.epoch(item.get('timestamp'))
            label = connection.get('name') or (str(date.year) if date else 'Дата неизвестна')
            return HistoricalPanorama(identifier, str(label)) if isinstance(identifier, str) and identifier else None
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
