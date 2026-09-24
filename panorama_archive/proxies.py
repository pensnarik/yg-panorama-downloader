#!/usr/bin/env python3
"""Load private SOCKS endpoints without exposing credentials in diagnostics."""
from pathlib import Path
from urllib.parse import urlsplit


class ProxyList:
    @classmethod
    def read(cls, filename=None):
        path = Path(filename or 'proxies.txt')
        if filename is None and not path.exists():
            return []
        lines = path.read_text(encoding='utf-8').splitlines()
        return list(dict.fromkeys(cls.parse(line.strip(), number) for number, line in enumerate(lines, 1)
                                 if line.strip() and not line.lstrip().startswith('#')))

    @staticmethod
    def parse(value, number):
        try:
            value = value if '://' in value else 'socks5h://' + value
            parsed = urlsplit(value)
            valid = parsed.scheme in ('socks5', 'socks5h', 'socks4', 'socks4a') and parsed.hostname and parsed.port
            if not valid or parsed.path or parsed.query or parsed.fragment or any(char.isspace() for char in value):
                raise ValueError()
            return value
        except ValueError:
            raise ValueError(f'Некорректный SOCKS-прокси в строке {number}') from None
