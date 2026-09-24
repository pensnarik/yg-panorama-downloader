#!/usr/bin/env python3
"""Explicit UTC calculation time and honest defaults from shooting evidence."""
from datetime import datetime, timezone


class SkyTime:
    def __init__(self):
        self.timestamp = None
        self.explanation = 'Текущее время'

    def from_metadata(self, shooting):
        if shooting.candidate and not shooting.conflict:
            self.timestamp = shooting.candidate.astimezone(timezone.utc)
            self.explanation = 'Время из ID панорамы, не подтверждено'
        elif shooting.day:
            self.timestamp = datetime(shooting.year, shooting.month, shooting.day, 12, tzinfo=timezone.utc)
            self.explanation = 'Известна только дата; условное время 12:00 UTC'
        else:
            self.timestamp = datetime.now(timezone.utc).replace(microsecond=0)
            self.explanation = 'Полная дата съёмки неизвестна; выбрано текущее время'

    def set_text(self, text):
        self.timestamp = datetime.strptime(text.strip(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        self.explanation = 'Выбранное время UTC'

    def text(self):
        return (self.timestamp or datetime.now(timezone.utc)).strftime('%Y-%m-%d %H:%M:%S')
