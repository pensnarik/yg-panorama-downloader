#!/usr/bin/env python3
"""Queue failures retain the subprocess stage and original worker diagnostics."""
import subprocess
from unittest import TestCase
from unittest.mock import Mock, patch
from panorama_archive.process_error import ProcessFailure
from panorama_archive.queue_worker import QueueWorker


class ProcessFailureTests(TestCase):
    def test_queue_persists_worker_identity_and_cause(self):
        worker = QueueWorker(Mock())
        worker.queue = Mock()
        job = {'panorama_id': 'target'}
        error = subprocess.CalledProcessError(1, ['python', '/project/pano.py'], stderr='[поток 3 | прокси 192.0.2.1] HTTP 503\n')
        with patch.object(worker, '_download', side_effect=error):
            worker._process(job)
        message = worker.queue.finish.call_args.args[1]
        self.assertIn('[поток 3 | прокси 192.0.2.1] HTTP 503', message)
        self.assertIn('Скачивание', message)

    def test_merge_traceback_is_reduced_to_cause(self):
        error = subprocess.CalledProcessError(1, ['python', 'merge.py'], stderr='Traceback (most recent call last):\nValueError: missing metadata\n')
        message = ProcessFailure.describe(error)
        self.assertIn('Склейка', message)
        self.assertIn('ValueError: missing metadata', message)
        self.assertNotIn('Traceback', message)

    def test_signal_without_stderr_remains_diagnostic(self):
        error = subprocess.CalledProcessError(-9, ['python', 'merge.py'], stderr='')
        self.assertIn('код завершения -9', ProcessFailure.describe(error))

    def test_proxy_password_in_exception_is_redacted(self):
        error = subprocess.CalledProcessError(1, ['pano.py'], stderr='ProxyError: socks5h://user:secret@192.0.2.1:1080\n')
        message = ProcessFailure.describe(error)
        self.assertNotIn('secret', message)
        self.assertIn('192.0.2.1', message)
