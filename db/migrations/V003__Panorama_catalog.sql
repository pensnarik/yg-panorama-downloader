-- Canonical provider/image records. Existing logs and raw metadata are retained.
-- Run transactionally as schema owner; then run panorama_archive.backfill.
create table aa.panorama (
    provider aa.panorama_provider not null,
    external_id text not null,
    panorama_id text,
    title text,
    latitude double precision,
    longitude double precision,
    altitude double precision,
    shooting_year smallint,
    shooting_month smallint check (shooting_month between 1 and 12),
    shooting_day smallint check (shooting_day between 1 and 31),
    date_precision text not null default 'unknown',
    date_source text not null default 'unknown',
    date_conflict boolean not null default false,
    time_candidate timestamptz,
    time_source text,
    provider_timestamp bigint,
    legacy_timestamp bigint,
    page_date text,
    origin_azimuth double precision,
    origin_tilt double precision,
    tile_width integer,
    tile_height integer,
    view_azimuth double precision,
    view_pitch double precision,
    span_horizontal double precision,
    span_vertical double precision,
    geometry_valid boolean,
    source_url text,
    client_observed_at timestamptz,
    received_at timestamptz,
    projection jsonb,
    images jsonb,
    default_view jsonb,
    annotation jsonb,
    raw_response jsonb,
    capture_envelope jsonb,
    latest_observation jsonb,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    primary key (provider, external_id)
);

create table aa.panorama_level (
    provider aa.panorama_provider not null,
    external_id text not null,
    level integer not null check (level >= 0),
    width integer not null check (width > 0),
    height integer not null check (height > 0),
    details jsonb not null,
    primary key (provider, external_id, level),
    foreign key (provider, external_id) references aa.panorama on delete cascade
);

-- Retain distinct provider responses even when a later arrival replaces the catalog.
create table aa.panorama_capture (
    provider aa.panorama_provider not null,
    external_id text not null,
    response_hash text not null,
    metadata jsonb not null,
    first_received_at timestamptz not null default now(),
    last_received_at timestamptz not null default now(),
    primary key (provider, external_id, response_hash),
    foreign key (provider, external_id) references aa.panorama on delete cascade
);

create index panorama_shooting_date_idx on aa.panorama (shooting_year, shooting_month, shooting_day);
create index panorama_provider_id_idx on aa.panorama (provider, panorama_id);
alter table aa.panorama owner to allarchive;
alter table aa.panorama_level owner to allarchive;
alter table aa.panorama_capture owner to allarchive;
comment on column aa.panorama.client_observed_at is 'Untrusted browser clock, not shooting time';
comment on column aa.panorama.time_candidate is 'Inferred from undocumented panorama ID; NOT verified shooting time';
comment on column aa.panorama.provider_timestamp is 'Raw provider timestamp; used for date only, not verified time of day';
