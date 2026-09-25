#!/usr/bin/env python3
"""Exercise real PostgreSQL queue transitions in an isolated temporary table."""
import os
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from panorama_archive.merge import ArchiveDatabase
from panorama_archive.queue import DownloadQueue


@skipUnless(os.environ.get('PANORAMA_DATABASE_TESTS') == '1', 'requires local PostgreSQL')
class QueueDatabaseTests(TestCase):
    def setUp(self):
        self.connection = psycopg.connect(**ArchiveDatabase.SETTINGS)
        self.addCleanup(self.connection.close)
        self.cursor = self.connection.cursor(row_factory=dict_row)
        migration = Path('db/migrations/V005__Download_queue.sql').read_text().split('create table ', 1)[1]
        self.cursor.execute(('create table ' + migration).replace('aa.panorama_download_queue', 'pg_temp.panorama_download_queue'))
        self.queue = DownloadQueue()
        patcher = patch.object(self.queue, '_execute', side_effect=self.execute)
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, query, parameters):
        self.cursor.execute(query.replace('aa.panorama_download_queue', 'pg_temp.panorama_download_queue'), parameters)
        return self.cursor.fetchone()

    def test_duplicate_click_preserves_active_claim(self):
        first = self.queue.enqueue('target', 'source')
        job = self.queue.claim()
        repeated = self.queue.enqueue('target', 'source')
        self.assertEqual(first['id'], repeated['id'])
        self.assertEqual(repeated['claim_token'], job['claim_token'])
        self.assertEqual(repeated['status'], 'downloading')
        self.assertIsNone(self.queue.claim())

    def test_failed_job_requires_retry_and_then_completes(self):
        self.queue.enqueue('target')
        job = self.queue.claim()
        self.queue.finish(job, 'Network unavailable')
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.queue.enqueue('target')['status'], 'pending')
        retry = self.queue.claim()
        self.assertEqual(retry['attempts'], 2)
        self.queue.finish(retry)
        self.assertIsNone(self.queue.claim())

    def test_expired_claim_is_recovered_and_old_worker_cannot_finish_it(self):
        self.queue.enqueue('target')
        old = self.queue.claim()
        self.cursor.execute("update pg_temp.panorama_download_queue set lease_until = now() - interval '1 second'")
        new = self.queue.claim()
        self.assertNotEqual(old['claim_token'], new['claim_token'])
        self.assertIsNone(self.queue.finish(old))
        self.assertIsNotNone(self.queue.heartbeat(new))
        self.assertIsNotNone(self.queue.resolve(new, 'tile-id'))
