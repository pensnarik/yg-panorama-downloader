-- Run transactionally. Browser titles survive API refreshes independently of logs.
alter table aa.panorama add column browser_title text;
update aa.panorama p set browser_title = source.view_name from (
    select distinct on (provider, external_id) provider, external_id, btrim(view_name) view_name
    from aa.panorama_log where nullif(btrim(view_name), '') is not null
    and lower(btrim(view_name)) <> 'unknown'
    order by provider, external_id, id desc) source
where p.provider = source.provider and p.external_id = source.external_id;

create table aa.panorama_download_queue (
    id bigserial primary key,
    panorama_id text not null unique check (panorama_id ~ '^[A-Za-z0-9_-]+$'),
    source_panorama_id text,
    title_hint text,
    external_id text,
    status text not null default 'pending' check (status in ('pending', 'downloading', 'completed', 'failed')),
    attempts integer not null default 0,
    claim_token uuid,
    lease_until timestamptz,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index panorama_download_queue_pending on aa.panorama_download_queue (status, created_at);
grant select, insert, update, delete on aa.panorama_download_queue to allarchive;
grant usage, select on sequence aa.panorama_download_queue_id_seq to allarchive;
