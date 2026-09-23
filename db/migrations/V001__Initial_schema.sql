create schema aa;

create sequence aa.panorama_log_id_seq start with 1 increment by 1;

create type aa.panorama_provider as enum ('yandex', 'google');

create table aa.panorama_log
(
    id                      bigint primary key default nextval('aa.panorama_log_id_seq'),
    provider                aa.panorama_provider not null,
    external_id             text not null,
    lat                     numeric,
    lon                     numeric,
    year                    smallint,
    view_name               text,
    tile_name               text,
    time_info               text,
    unix_timestamp          bigint,
    created_at              timestamptz not null default now()
);

alter table aa.panorama_log owner to allarchive;

create table aa.panorama_log_meta (
    id                      bigint primary key,
    meta                    jsonb
);

alter table aa.panorama_log_meta owner to allarchive;

alter table only aa.panorama_log_meta
    add constraint panorama_log_meta_id_fkey foreign key (id) references aa.panorama_log(id);
