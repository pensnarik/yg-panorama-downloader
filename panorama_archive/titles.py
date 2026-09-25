#!/usr/bin/env python3
"""Preserve useful addresses when API responses omit their point name."""


class CatalogTitles:
    REPAIR = '''update aa.panorama p set title = source.view_name from (
        select distinct on (provider, external_id) provider, external_id, btrim(view_name) view_name
        from aa.panorama_log where nullif(btrim(view_name), '') is not null
        and lower(btrim(view_name)) <> 'unknown'
        order by provider, external_id, id desc) source
        where p.provider = source.provider and p.external_id = source.external_id
        and (nullif(btrim(p.title), '') is null or lower(btrim(p.title)) = 'unknown')'''

    @staticmethod
    def normalize(value):
        text = value.strip() if isinstance(value, str) else ''
        return text if text and text.lower() != 'unknown' else None

    @staticmethod
    def assignment(strong, has_metadata):
        incoming = "nullif(btrim(excluded.title), '')"
        existing = "nullif(btrim(aa.panorama.title), '')"
        preferred = f'coalesce({incoming}, {existing})'
        if strong:
            return 'title = coalesce(aa.panorama.browser_title, ' + incoming + ', ' + existing + ')'
        return 'title = ' + preferred

    @classmethod
    def repair(cls, cursor):
        cursor.execute(cls.REPAIR)
        return cursor.rowcount
