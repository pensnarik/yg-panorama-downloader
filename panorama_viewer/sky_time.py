#!/usr/bin/env python3
"""Explicit UTC calculation time and honest defaults from shooting evidence."""
from datetime import datetime, timezone, timedelta


class SkyTime:
    def __init__(self):
        self.timestamp = None
        self.offset_minutes = 0
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
        local = datetime.strptime(text.strip(), '%Y-%m-%d %H:%M:%S').replace(tzinfo=self.zone)
        self.timestamp = local.astimezone(timezone.utc)
        self.explanation = f'Выбранное время {self.zone_name}'

    def text(self):
        return (self.timestamp or datetime.now(timezone.utc)).astimezone(self.zone).strftime('%Y-%m-%d %H:%M:%S')


    @property
    def zone(self):
        return timezone(timedelta(minutes=self.offset_minutes))

    @property
    def zone_name(self):
        sign = '+' if self.offset_minutes >= 0 else '-'
        hours, minutes = divmod(abs(self.offset_minutes), 60)
        return f'UTC{sign}{hours:02d}:{minutes:02d}'

    def set_offset(self, minutes):
        if not isinstance(minutes, int) or not -720 <= minutes <= 840 or minutes % 15:
            raise ValueError('Смещение должно быть от UTC−12:00 до UTC+14:00 с шагом 15 минут')
        self.offset_minutes = minutes
