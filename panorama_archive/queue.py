#!/usr/bin/env python3
"""Durable queue with atomic claims and renewable leases for crashed workers."""
import re
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from .merge import ArchiveDatabase


class QueueQueries:
    ENQUEUE = '''insert into aa.panorama_download_queue (panorama_id, source_panorama_id, title_hint)
        values (%s, %s, %s) on conflict (panorama_id) do update set
        status = case when aa.panorama_download_queue.status in ('failed', 'completed') then 'pending'
                      else aa.panorama_download_queue.status end,
        error_message = null, updated_at = now() returning *'''
    CLAIM = '''update aa.panorama_download_queue set status = 'downloading', claim_token = %s,
        lease_until = now() + interval '5 minutes', attempts = attempts + 1, updated_at = now()
        where id = (select id from aa.panorama_download_queue where status = 'pending'
        or (status = 'downloading' and lease_until < now()) order by created_at, id
        for update skip locked limit 1) returning *'''
    HEARTBEAT = '''update aa.panorama_download_queue set lease_until = now() + interval '5 minutes'
        where id = %s and claim_token = %s and status = 'downloading' returning id'''
    FINISH = '''update aa.panorama_download_queue set status = %s, error_message = %s,
        lease_until = null, updated_at = now() where id = %s and claim_token = %s and status = 'downloading' returning id'''
    RESOLVE = '''update aa.panorama_download_queue set external_id = %s
        where id = %s and claim_token = %s and status = 'downloading' returning id'''


class DownloadQueue:
    @staticmethod
    def _execute(query, parameters):
        with psycopg.connect(**ArchiveDatabase.SETTINGS, connect_timeout=3,
                             options='-c statement_timeout=5000') as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, parameters)
                return cursor.fetchone()

    def enqueue(self, identifier, source=None, title=None):
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
            raise ValueError('Некорректный ID панорамы')
        return self._execute(QueueQueries.ENQUEUE, [identifier, source, title])

    def claim(self):
        return self._execute(QueueQueries.CLAIM, [uuid4()])

    def heartbeat(self, job):
        return self._execute(QueueQueries.HEARTBEAT, [job['id'], job['claim_token']])

    def resolve(self, job, image_id):
        return self._execute(QueueQueries.RESOLVE, [image_id, job['id'], job['claim_token']])

    def finish(self, job, error=None):
        status = 'failed' if error else 'completed'
        return self._execute(QueueQueries.FINISH, [status, error, job['id'], job['claim_token']])
