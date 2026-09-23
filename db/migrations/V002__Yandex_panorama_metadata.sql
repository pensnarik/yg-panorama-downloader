-- Run once against the existing database before loading extension v1.1.
-- image_id is the directory / tile ID, panorama_id is the provider's long ID.
create table aa.yandex_panorama_metadata (
    image_id text primary key,
    panorama_id text not null,
    captured_at timestamptz not null,
    metadata jsonb not null,
    updated_at timestamptz not null default now()
);

create index yandex_panorama_metadata_panorama_id_idx
    on aa.yandex_panorama_metadata (panorama_id);

alter table aa.yandex_panorama_metadata owner to allarchive;
