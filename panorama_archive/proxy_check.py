#!/usr/bin/env python3
"""Independent TCP, SOCKS authentication and HTTP proxy diagnostics."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import socket
from urllib.parse import urlsplit, unquote
import requests
from .proxies import ProxyList


@dataclass(frozen=True)
class ProxyEntry:
    line: int
    url: str
    commented: bool

    @property
    def endpoint(self):
        parsed = urlsplit(self.url)
        return parsed.hostname, parsed.port

    @property
    def label(self):
        host, port = self.endpoint
        host = f'[{host}]' if ':' in host else host
        return f'строка {self.line} · {host}:{port}' + (' · закомментирован' if self.commented else '')


class DiagnosticProxyFile:
    @classmethod
    def read(cls, path):
        entries, errors = [], []
        for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
            value, commented = cls._line(line)
            if value is None:
                continue
            cls._append(entries, errors, number, value, commented)
        return entries, errors

    @staticmethod
    def _append(entries, errors, number, value, commented):
        try:
            entries.append(ProxyEntry(number, ProxyList.parse(value, number), commented))
        except ValueError:
            errors.append(f'Строка {number}: некорректный адрес прокси (значение скрыто)')

    @staticmethod
    def _line(line):
        value, commented = line.strip().lstrip('#').strip(), line.lstrip().startswith('#')
        if not value or (commented and '://' not in value and not value.rsplit(':', 1)[-1].isdigit()):
            return None, commented
        return value, commented


class SocksHandshake:
    @staticmethod
    def receive(connection, length):
        result = b''
        while len(result) < length:
            chunk = connection.recv(length - len(result))
            if not chunk:
                raise ConnectionError('SOCKS connection closed')
            result += chunk
        return result

    @classmethod
    def check(cls, entry, timeout):
        parsed = urlsplit(entry.url)
        if parsed.scheme in ('socks4', 'socks4a'):
            return True, 'SOCKS4: отдельной проверки пароля нет; доступ проверяется HTTP-запросами'
        with socket.create_connection(entry.endpoint, timeout=timeout) as connection:
            methods = b'\x00\x02' if parsed.username is not None else b'\x00'
            connection.sendall(b'\x05' + bytes([len(methods)]) + methods)
            version, method = cls.receive(connection, 2)
            return cls._selected(connection, parsed, version, method)

    @classmethod
    def _selected(cls, connection, parsed, version, method):
        if version != 5:
            return False, 'сервер не отвечает по протоколу SOCKS5'
        if method == 0:
            return True, 'SOCKS5 без авторизации; логин и пароль не проверены сервером'
        if method == 2 and parsed.username is not None:
            return cls._password(connection, parsed)
        return False, 'сервер отклонил предложенные методы авторизации'

    @classmethod
    def _password(cls, connection, parsed):
        username = unquote(parsed.username).encode('utf-8')
        password = unquote(parsed.password or '').encode('utf-8')
        if not 1 <= len(username) <= 255 or not 1 <= len(password) <= 255:
            return False, 'логин и пароль должны занимать от 1 до 255 байт'
        connection.sendall(b'\x01' + bytes([len(username)]) + username + bytes([len(password)]) + password)
        version, status = cls.receive(connection, 2)
        return (True, 'логин и пароль приняты') if version == 1 and status == 0 else (False, 'авторизация отклонена')


class ProxyDiagnostic:
    HOSTS = ('yandex.ru', 'google.com', 'mail.ru', 'wayfarer-crm.com')

    def __init__(self, timeout):
        self.timeout = timeout

    def check(self, entry):
        results = [('TCP-порт', *self._port(entry))]
        authentication = self._authentication(entry) if results[0][1] else (False, 'не проверено: порт недоступен')
        results.append(('Авторизация', *authentication))
        for host in self.HOSTS:
            outcome = self._http(entry, host) if authentication[0] else (False, 'не проверено: нет SOCKS-соединения')
            results.append((f'http://{host}', *outcome))
        return entry, results

    def _port(self, entry):
        try:
            with socket.create_connection(entry.endpoint, timeout=self.timeout):
                return True, 'соединение установлено'
        except OSError as error:
            return False, self._reason(error)

    def _authentication(self, entry):
        try:
            return SocksHandshake.check(entry, self.timeout)
        except OSError as error:
            return False, self._reason(error)

    def _http(self, entry, host):
        try:
            with requests.Session() as session:
                session.trust_env = False
                session.proxies = {'http': entry.url, 'https': entry.url}
                with session.get(f'http://{host}/', timeout=self.timeout, allow_redirects=False, stream=True) as response:
                    return response.status_code < 400, self._status(response)
        except requests.RequestException as error:
            return False, self._reason(error)

    @staticmethod
    def _status(response):
        status = response.status_code
        if 300 <= status < 400:
            return f'HTTP {status}: получен редирект; переход не выполнялся'
        return f'HTTP {status}' + (': сервер или прокси вернул ошибку' if status >= 400 else ': ответ получен')

    @staticmethod
    def _reason(error):
        if isinstance(error, (TimeoutError, requests.Timeout)):
            return 'истекло время ожидания'
        if isinstance(error, ConnectionRefusedError):
            return 'соединение отклонено'
        if isinstance(error, socket.gaierror):
            return 'ошибка разрешения имени прокси'
        return f'ошибка соединения ({type(error).__name__}); проверьте доступность и настройки прокси'


class ProxyCheckCommand:
    @classmethod
    def run(cls, arguments=None):
        options = cls._parse(arguments)
        try:
            entries, errors = DiagnosticProxyFile.read(options.file)
        except OSError:
            print('Не удалось прочитать файл прокси.')
            return 1
        for error in errors:
            print(error)
        return cls._check(entries, options) or int(bool(errors))

    @staticmethod
    def _parse(arguments):
        parser = argparse.ArgumentParser(description='Проверка всех SOCKS-прокси, включая строки с #')
        parser.add_argument('--file', type=Path, default=Path('proxies.txt'))
        parser.add_argument('--timeout', type=float, default=5)
        parser.add_argument('--workers', type=int, default=4)
        parser.add_argument('--only-failed', action='store_true', help='выводить только прокси с ошибками')
        options = parser.parse_args(arguments)
        if not 0 < options.timeout <= 60 or not 1 <= options.workers <= 32:
            parser.error('timeout: от 0 до 60 секунд; workers: от 1 до 32')
        return options

    @classmethod
    def _check(cls, entries, options):
        if not entries:
            print('Прокси для проверки не найдены.')
            return 1
        print(f'Проверка {len(entries)} прокси; HTTP без перехода по редиректам.', flush=True)
        failed = 0
        with ThreadPoolExecutor(max_workers=options.workers) as executor:
            for entry, results in executor.map(ProxyDiagnostic(options.timeout).check, entries):
                failed += cls._report(entry, results, options.only_failed)
        return int(failed > 0)

    @staticmethod
    def _report(entry, results, only_failed=False):
        failed = any(not success for stage, success, message in results)
        if only_failed and not failed:
            return 0
        print(f'\n[{entry.label}]', flush=True)
        for stage, success, message in results:
            print(f'  {"OK" if success else "FAIL"} · {stage}: {message}', flush=True)
        return int(failed)
