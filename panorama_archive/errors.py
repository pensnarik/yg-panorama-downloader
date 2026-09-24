#!/usr/bin/env python3
"""Safe, actionable download diagnostics without proxy credentials."""
import requests


class ProxyDownloadError(RuntimeError):
    """An already formatted worker failure suitable for terminal output."""


class TileHttpError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'Сервер тайлов вернул HTTP {status}')


class ProxyErrorMessage:
    @classmethod
    def describe(cls, error):
        if isinstance(error, TileHttpError):
            return f'Сервер тайлов вернул HTTP {error.status}; загрузка остановлена.'
        if isinstance(error, requests.exceptions.SSLError):
            return 'Ошибка TLS при соединении через прокси; проверьте сертификат и настройки прокси.'
        if isinstance(error, (requests.exceptions.Timeout, TimeoutError)):
            return 'Истекло время ожидания соединения или ответа через прокси.'
        if isinstance(error, (requests.exceptions.ConnectionError, ConnectionError)):
            return cls._connection(error) + f' ({type(error).__name__})'
        return cls._other(error)

    CONNECTION_REASONS = (
        (('auth', '0x02'), 'Прокси отклонил авторизацию или доступ; проверьте логин, пароль и правила доступа.'),
        (('refused',), 'Соединение отклонено; проверьте доступность прокси и его порт.'),
        (('timed out', 'timeout'), 'Истекло время ожидания соединения или ответа через прокси.'),
        (('name resolution', 'getaddrinfo'), 'Не удалось разрешить имя узла при соединении через прокси; проверьте DNS.'),
    )

    @classmethod
    def _connection(cls, error):
        text = str(error).lower()
        for patterns, explanation in cls.CONNECTION_REASONS:
            if any(pattern in text for pattern in patterns):
                return explanation
        return 'Не удалось установить соединение через прокси; проверьте его доступность и настройки.'

    @staticmethod
    def _other(error):
        if isinstance(error, OSError):
            return 'Ошибка ввода-вывода; проверьте соединение, права на каталог и свободное место.'
        if isinstance(error, requests.exceptions.RequestException):
            return 'Не удалось выполнить HTTP-запрос через прокси; проверьте настройки соединения.'
        return f'Загрузка остановлена из-за внутренней ошибки ({type(error).__name__}).'
