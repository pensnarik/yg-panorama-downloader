-- Apply in a single transaction after V003, while writers are stopped.
create table aa.panorama_payload (
    provider aa.panorama_provider not null,
    external_id text not null,
    projection jsonb,
    images jsonb,
    default_view jsonb,
    annotation jsonb,
    raw_response jsonb,
    capture_envelope jsonb,
    latest_observation jsonb,
    primary key (provider, external_id),
    foreign key (provider, external_id) references aa.panorama on delete cascade
);

insert into aa.panorama_payload (provider, external_id, projection, images, default_view, annotation, raw_response, capture_envelope, latest_observation)
select provider, external_id, projection, images, default_view, annotation, raw_response, capture_envelope, latest_observation from aa.panorama;

alter table aa.panorama
    drop column projection,
    drop column images,
    drop column default_view,
    drop column annotation,
    drop column raw_response,
    drop column capture_envelope,
    drop column latest_observation;

grant select, insert, update, delete on aa.panorama_payload to allarchive;
