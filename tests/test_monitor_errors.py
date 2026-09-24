#!/usr/bin/env python3
"""Worker identities survive subprocess failure and cancellation of other workers."""
import io
import subprocess
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase
from unittest.mock import Mock, patch
from panorama_archive.monitor import DownloadMonitor
from panorama_archive.parallel import ProxyDownloadPool
from panorama_archive.logging import DownloadLog


class MonitorErrorTests(TestCase):
    def test_subprocess_error_keeps_worker_identity_in_final_message(self):
        details = 'Traceback (most recent call last):\nRuntimeError: [поток 2 | прокси 192.0.2.2] Загрузка остановлена (ConnectionError)\n'
        failure = subprocess.CalledProcessError(1, ['pano.py'], stderr=details)
        with patch('subprocess.run', side_effect=failure) as execute, redirect_stdout(io.StringIO()) as output:
            self.run_failed_command()
        self.assertEqual(output.getvalue(), '[поток 2 | прокси 192.0.2.2] Загрузка остановлена (ConnectionError)\n')
        self.assertEqual(execute.call_args.kwargs['stderr'], subprocess.PIPE)
        self.assertNotIn('stdout', execute.call_args.kwargs)

    def run_failed_command(self):
        try:
            DownloadMonitor._execute('pano.py', 'sample', 0)
        except subprocess.CalledProcessError as error:
            DownloadMonitor._report_failure(error)

    def test_error_without_worker_identity_still_explains_failure(self):
        failure = subprocess.CalledProcessError(1, ['merge.py'], stderr='ValueError: missing metadata\n')
        with redirect_stdout(io.StringIO()) as output:
            DownloadMonitor._report_failure(failure)
        self.assertIn('missing metadata', output.getvalue())

    def test_cancellation_does_not_replace_original_proxy_failure(self):
        pool = ProxyDownloadPool(Mock(provider=Mock(columns=0)), [], .5)
        with ThreadPoolExecutor(max_workers=1) as executor:
            original = executor.submit(self.fail, pool, 2, ConnectionError()).result()
            secondary = executor.submit(self.fail, pool, 1, InterruptedError()).result()
        self.assertIs(original, secondary)
        self.assertIn('[поток 2 | прокси 192.0.2.2]', str(secondary))
        self.assertIn('ConnectionError', str(secondary))

    def fail(self, pool, number, error):
        DownloadLog.identify(number, f'socks5h://user:secret@192.0.2.{number}:1080')
        return pool._failure(error)
