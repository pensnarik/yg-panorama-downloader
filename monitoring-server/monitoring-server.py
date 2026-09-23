#!/usr/bin/env python3

from flask import Flask, jsonify, render_template, request

import psycopg

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from flask_cors import CORS
from panorama_metadata import normalize_capture

app = Flask(__name__)
CORS(app)

# Параметры подключения к базе данных
DB_CONFIG = {
    "dbname": "panoramas",
    "user": "allarchive",
    "password": "allarchive",
    "host": "localhost",
    "port": 5432
}

def yandex_panorama_exists(conn, id: str):
    query = "select count(*) from aa.yandex_panorama where id = %s"

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, [id])
        result = cursor.fetchone()

    return result['count'] == 1


def save_panorama_meta(conn, id: int, meta: dict):
    query = "insert into aa.panorama_log_meta (id, meta) " \
            "values (%s, %s) "

    with conn.cursor() as cursor:
        cursor.execute(query, [id, meta])

    return True


@app.route('/aa/yandex-panorama-metadata', methods=['POST'])
def yandex_panorama_metadata():
    try:
        metadata = normalize_capture(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({'status': 'error', 'error': str(error)}), 400

    with psycopg.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """insert into aa.yandex_panorama_metadata
                   (image_id, panorama_id, captured_at, metadata)
                   values (%s, %s, %s, %s)
                   on conflict (image_id) do update set
                       panorama_id = excluded.panorama_id,
                       captured_at = excluded.captured_at,
                       metadata = excluded.metadata, updated_at = now()
                   where excluded.captured_at > aa.yandex_panorama_metadata.captured_at
                   returning image_id""",
                [metadata['imageId'], metadata['panoramaId'], metadata['capturedAt'], Jsonb(metadata)]
            )
            changed = cursor.fetchone()
            if changed:
                # The downloader still discovers images through panorama_log.
                # Coordinates here come from this response, not a changing tab URL.
                point = metadata.get('position') or {}
                coordinates = point.get('coordinates') or []
                lon, lat = (coordinates[:2] if len(coordinates) >= 2 else (None, None))
                cursor.execute(
                    """insert into aa.panorama_log
                       (provider, external_id, lat, lon, unix_timestamp, view_name)
                       values ('yandex', %s, %s, %s, %s, %s) returning id""",
                    [metadata['imageId'], lat, lon, metadata['timestamp'], point.get('name')]
                )
                log_id = cursor.fetchone()[0]
                save_panorama_meta(conn, log_id, Jsonb({
                    'metadata_image_id': metadata['imageId'],
                    'panorama_id_from_url': metadata['panoramaId'],
                    'source': 'panorama-response'
                }))

    return jsonify({'status': 'ok', 'imageId': metadata['imageId'],
                    'geometryFieldsPresent': metadata['geometryFieldsPresent'],
                    'missingFields': metadata['missingFields']})


@app.route('/aa/yandex-panorama-metadata/<image_id>', methods=['GET'])
def get_yandex_panorama_metadata(image_id):
    """Export an offline manifest without calling any Yandex service."""
    with psycopg.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cursor:
            cursor.execute('select metadata from aa.yandex_panorama_metadata where image_id = %s',
                           [image_id])
            row = cursor.fetchone()
    if row is None:
        return jsonify({'status': 'error', 'error': 'Metadata not found'}), 404
    return jsonify(row[0])


@app.route('/aa/google-panorama', methods=['POST'])
def google_panorama():
    data = request.json
    print(data)

    lon, lat = data['panoramaPoint'].split(',')

    if data['year'] == 'unknown':
        year = None
    else:
        year = data['year']

    if data['view'] == 'unknown':
        view = None
    else:
        view = data['view']

    unix_timestamp = None

    query = "insert into aa.panorama_log " \
            "(provider, external_id, lat, lon, time_info, view_name, tile_name) " \
            "values (%s, %s, %s, %s, %s, %s, %s) " \
            "returning id"

    with psycopg.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                query,
                [
                    'google', data['panoramaId'], lat, lon, year, view, data['tileName']
                ]
            )

    return jsonify({"status": "ok"})


@app.route('/aa/yandex-panorama', methods=['POST'])
def yandex_panorama():
    """
    Сохраняет данные о панорамах Yandex в базу данных.
    """
    data = request.json
    print(data)

    query = "insert into aa.panorama_log " \
            "(provider, external_id, lat, lon, unix_timestamp, year, view_name, tile_name) " \
            "values (%s, %s, %s, %s, %s, %s, %s, %s) " \
            "returning id"

    point = data.get('panoramaPoint')
    lon, lat = point.split(',') if point else (None, None)

    url_id = data.get('panoramaIdFromURL')
    suffix = url_id.split('_')[-1] if url_id else ''
    unix_timestamp = int(suffix) if suffix.isdigit() else None

    if data['year'] == 'unknown':
        year = None
    else:
        year = data['year']

    if data['view'] == 'unknown':
        view = None
    else:
        view = data['view']

    meta = {
        'panarama_id_from_url': url_id,  # Retain legacy key for existing consumers.
        'panorama_id_from_url': url_id,
        'observed_view': {'direction': data.get('direction'), 'span': data.get('span')},
        'source': 'tile-request',
        # DOM/URL context is only an observation, not authoritative image geometry.
    }

    with psycopg.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cursor:

            cursor.execute(
                query,
                [
                    'yandex', data['panoramaId'], lat, lon, unix_timestamp, year,
                    view, data['tileName']
                ]
            )
            id = cursor.fetchone()

            print(f"{id=}")

            save_panorama_meta(conn, id[0], Jsonb(meta))

    return jsonify({"status": "ok"})


@app.route('/')
def index():
    return "OK"


if __name__ == '__main__':
    app.run(debug=True)
