#!/usr/bin/env python3
"""Separate provider dates, unverified ID times and metadata collection times."""
from dataclasses import dataclass
from datetime import datetime, timezone
import re


class DateEvidence:
    @staticmethod
    def epoch(value):
        if isinstance(value, bool) or not re.fullmatch(r'\d{10}', str(value)):
            return None
        result = datetime.fromtimestamp(int(value), timezone.utc)
        return result if 2000 <= result.year <= 2099 else None

    @classmethod
    def identifier_time(cls, identifier):
        match = re.fullmatch(r'\d+_\d+_\d+_(\d{10})', identifier or '')
        return cls.epoch(match[1]) if match else None

    @staticmethod
    def observed_at(value):
        try:
            instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return instant.isoformat() if instant.utcoffset() is not None else None
        except (ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def partial(value):
        text = str(value or '').strip()
        match = re.fullmatch(r'(20\d{2})(?:-(0[1-9]|1[0-2]))?', text)
        if match:
            return int(match[1]), int(match[2]) if match[2] else None
        return DateEvidence._named_month(text)

    @staticmethod
    def _named_month(text):
        months = ('jan янв', 'feb фев', 'mar мар', 'apr апр', 'may мая май', 'jun июн',
                  'jul июл', 'aug авг', 'sep сен', 'oct окт', 'nov ноя', 'dec дек')
        year = re.search(r'\b(20\d{2})\b', text)
        month = next((index for index, names in enumerate(months, 1)
                      if any(re.search(r'\b' + name, text.lower()) for name in names.split())), None)
        return (int(year[1]), month) if year else (None, None)


@dataclass(frozen=True)
class ShootingDate:
    year: int | None = None
    month: int | None = None
    day: int | None = None
    source: str = 'unknown'
    candidate: datetime | None = None
    conflict: bool = False
    provider_timestamp: int | None = None

    @classmethod
    def from_data(cls, data):
        provider = DateEvidence.epoch(data.get('timestamp'))
        candidate = DateEvidence.identifier_time(data.get('panoramaId'))
        chosen = provider or candidate
        if chosen is None:
            return cls()
        conflict = bool(provider and candidate and abs((provider.date() - candidate.date()).days) > 1)
        return cls(chosen.year, chosen.month, chosen.day, 'api-date' if provider else 'id-inferred',
                   candidate, conflict, int(provider.timestamp()) if provider else None)

    @classmethod
    def from_observation(cls, provider, values):
        candidate = DateEvidence.identifier_time(values.get('panoramaIdFromURL')) if provider == 'yandex' else None
        year, month = DateEvidence.partial(values.get('year'))
        if candidate:
            return cls(candidate.year, candidate.month, candidate.day, 'id-inferred', candidate,
                       year is not None and year != candidate.year)
        return cls(year, month, source='page-label' if year else 'unknown')

    @property
    def precision(self):
        return 'day' if self.day else 'month' if self.month else 'year' if self.year else 'unknown'

    def columns(self):
        return {'shooting_year': self.year, 'shooting_month': self.month, 'shooting_day': self.day,
                'date_precision': self.precision, 'date_source': self.source, 'date_conflict': self.conflict,
                'time_candidate': self.candidate.isoformat() if self.candidate else None,
                'time_source': 'panorama-id-unverified' if self.candidate else None,
                'provider_timestamp': self.provider_timestamp}

    def label(self):
        if self.year is None:
            return 'Съёмка: дата и время неизвестны'
        sources = {'api-date': 'дата API', 'id-inferred': 'по ID, не подтверждено', 'page-label': 'надпись на странице'}
        text = f'Съёмка: {self._date_text()} ({sources.get(self.source, self.source)})'
        if self.conflict:
            return text + ' · источники расходятся, время не подтверждено'
        if self.candidate:
            return text + f' · предположительно {self.candidate:%d.%m.%Y %H:%M:%S} UTC, из ID'
        return text + ' · время неизвестно'

    @classmethod
    def from_columns(cls, row):
        candidate = row['time_candidate'].astimezone(timezone.utc) if row['time_candidate'] else None
        return cls(row['shooting_year'], row['shooting_month'], row['shooting_day'], row['date_source'],
                   candidate, row['date_conflict'], row['provider_timestamp'])

    def _date_text(self):
        if self.day:
            return f'{self.day:02d}.{self.month:02d}.{self.year}'
        return f'{self.month:02d}.{self.year}' if self.month else str(self.year)
