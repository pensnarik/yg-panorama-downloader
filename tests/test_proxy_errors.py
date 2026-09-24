#!/usr/bin/env python3
"""User-facing proxy failures never expose tracebacks or credentials."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import subprocess
from unittest import TestCase
from unittest.mock import patch
import requests
from panorama_archive.errors import ProxyDownloadError, ProxyErrorMessage, TileHttpError
from panorama_archive.download import DownloadCommand
from panorama_archive.monitor import DownloadMonitor


class ProxyErrorTests(TestCase):
    def test_connection_errors_explain_the_reason_without_credentials(self):
        cases = [('authentication failed', 'авторизацию'), ('Connection refused', 'отклонено'),
                 ('timed out', 'время ожидания'), ('name resolution failed', 'DNS')]
        for detail, expected in cases:
            message = ProxyErrorMessage.describe(requests.ConnectionError(detail + ' user:secret@host'))
            self.assertIn(expected, message)
            self.assertNotIn('secret', message)

    def test_timeout_tls_and_http_status_have_distinct_messages(self):
        for error, expected in ((requests.ReadTimeout(), 'время ожидания'), (requests.exceptions.SSLError(), 'TLS'),
                                (TileHttpError(503), 'HTTP 503')):
            self.assertIn(expected, ProxyErrorMessage.describe(error))

    def test_command_reports_worker_error_without_traceback(self):
        message = '[поток 2 | прокси 192.0.2.2] Соединение отклонено; проверьте порт.'
        with patch.object(DownloadCommand, '_run', side_effect=ProxyDownloadError(message)):
            with redirect_stderr(StringIO()) as output:
                self.assertEqual(DownloadCommand.run('yandex'), 1)
        self.assertEqual(output.getvalue(), message + '\n')
        self.assertNotIn('Traceback', output.getvalue())

    def test_monitor_forwards_plain_worker_error_without_main_thread_prefix(self):
        message = '[поток 2 | прокси 192.0.2.2] Соединение отклонено; проверьте порт.'
        failure = subprocess.CalledProcessError(1, ['pano.py'], stderr=message + '\n')
        with redirect_stdout(StringIO()) as output:
            DownloadMonitor._report_failure(failure)
        self.assertEqual(output.getvalue(), message + '\n')
