#!/usr/bin/env python3
"""Proxy diagnosis checks authentication separately and never follows HTTPS redirects."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from panorama_archive.proxy_check import DiagnosticProxyFile, ProxyEntry, SocksHandshake, ProxyDiagnostic, ProxyCheckCommand


class DiagnosticFileTests(TestCase):
    def test_commented_endpoints_are_included_without_exposing_password(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'proxies.txt'
            path.write_text('# Disabled proxies:\n # socks5h://user:secret@127.0.0.1:1080\n127.0.0.2:1081\n')
            entries, errors = DiagnosticProxyFile.read(path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(errors, [])
        self.assertTrue(entries[0].commented)
        self.assertNotIn('secret', entries[0].label)


class ProxyReportTests(TestCase):
    def test_only_failed_option_defaults_to_false_and_can_be_enabled(self):
        self.assertFalse(ProxyCheckCommand._parse([]).only_failed)
        self.assertTrue(ProxyCheckCommand._parse(['--only-failed']).only_failed)

    def test_successful_proxy_is_hidden_only_when_requested(self):
        entry = ProxyEntry(1, 'socks5h://127.0.0.1:1080', False)
        with patch('builtins.print') as output:
            self.assertEqual(ProxyCheckCommand._report(entry, [('TCP', True, 'ok')], True), 0)
            output.assert_not_called()
            self.assertEqual(ProxyCheckCommand._report(entry, [('TCP', True, 'ok')]), 0)
            self.assertEqual(output.call_count, 2)

    def test_failed_proxy_keeps_all_stages_and_failure_status(self):
        entry = ProxyEntry(1, 'socks5h://127.0.0.1:1080', True)
        results = [('TCP', True, 'ok'), ('HTTP', False, 'timeout')]
        with patch('builtins.print') as output:
            self.assertEqual(ProxyCheckCommand._report(entry, results, True), 1)
        self.assertEqual(output.call_count, 3)
        self.assertIn('OK', output.call_args_list[1].args[0])
        self.assertIn('FAIL', output.call_args_list[2].args[0])


class SocksHandshakeTests(TestCase):
    def check_reply(self, chunks):
        entry = ProxyEntry(1, 'socks5h://user:p%40ss@127.0.0.1:1080', False)
        connection = Mock(recv=Mock(side_effect=chunks))
        with patch('socket.create_connection') as connect:
            connect.return_value.__enter__.return_value = connection
            outcome = SocksHandshake.check(entry, 1)
        return outcome, connection

    def test_authentication_sends_decoded_credentials_and_reads_fragmented_reply(self):
        outcome, connection = self.check_reply([b'\x05', b'\x02', b'\x01\x00'])
        self.assertTrue(outcome[0])
        self.assertEqual(connection.sendall.call_args.args[0], b'\x01\x04user\x04p@ss')

    def test_rejected_credentials_are_distinguished(self):
        outcome, connection = self.check_reply([b'\x05\x02', b'\x01\x01'])
        self.assertFalse(outcome[0])
        self.assertIn('авторизация отклонена', outcome[1])

    def test_no_authentication_does_not_claim_password_verified(self):
        outcome, connection = self.check_reply([b'\x05\x00'])
        self.assertTrue(outcome[0])
        self.assertIn('не проверены', outcome[1])
        self.assertEqual(connection.sendall.call_count, 1)

    def test_closed_socket_is_handled(self):
        with self.assertRaises(ConnectionError):
            SocksHandshake.receive(Mock(recv=Mock(return_value=b'')), 2)


class HttpDiagnosticTests(TestCase):
    def test_http_redirect_is_reported_without_following_or_using_environment(self):
        with patch('requests.Session') as constructor:
            session = constructor.return_value.__enter__.return_value
            session.get.return_value.__enter__.return_value.status_code = 301
            success, message = ProxyDiagnostic(2)._http(ProxyEntry(1, 'socks5h://127.0.0.1:1080', False), 'yandex.ru')
        self.assertTrue(success)
        self.assertFalse(session.trust_env)
        session.get.assert_called_once_with('http://yandex.ru/', timeout=2, allow_redirects=False, stream=True)
        self.assertIn('301', message)

    def test_closed_port_skips_authentication_and_http(self):
        diagnostic = ProxyDiagnostic(1)
        with patch.object(diagnostic, '_port', return_value=(False, 'refused')), patch.object(diagnostic, '_http') as http:
            entry, results = diagnostic.check(ProxyEntry(1, 'socks5h://127.0.0.1:1080', True))
        self.assertEqual(len(results), 6)
        self.assertFalse(any(result[1] for result in results))
        http.assert_not_called()
