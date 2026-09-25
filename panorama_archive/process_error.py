#!/usr/bin/env python3
"""Persist concise subprocess failures without tracebacks or proxy credentials."""
from pathlib import Path
import re


class ProcessFailure:
    @staticmethod
    def detail(error):
        text = getattr(error, 'stderr', None) or ''
        match = re.search(r'^(?:RuntimeError: )?(\[поток \d+ \| прокси [^\]\r\n]+\] .+)$', text, re.MULTILINE)
        detail = match[1] if match else next((line.strip() for line in reversed(text.splitlines()) if line.strip()), '')
        return re.sub(r'(?i)((?:socks[45]h?|socks4a|https?)://)[^\s/]*@', r'\1***@', detail)[:2000]

    @classmethod
    def describe(cls, error):
        arguments = error.cmd if isinstance(error.cmd, (list, tuple)) else []
        script = next((Path(str(item)).name for item in arguments if str(item).endswith('.py')), '')
        stage = 'Склейка' if script == 'merge.py' else 'Скачивание' if script in ('pano.py', 'pano-google.py') else 'Процесс'
        detail = cls.detail(error)
        outcome = f'{stage}: код завершения {error.returncode}'
        return f'{detail} ({outcome})' if detail else outcome + '; stderr пуст.'
