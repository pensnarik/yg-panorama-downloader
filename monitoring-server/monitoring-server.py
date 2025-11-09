#!/usr/bin/env python3

from flask import Flask, jsonify, render_template, request

import psycopg

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Параметры подключения к базе данных
DB_CONFIG = {
    "dbname": "allarchive",
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

    lon, lat = data['panoramaPoint'].split(',')

    if data['panoramaIdFromURL'] is not None:
        unix_timestamp = data['panoramaIdFromURL'].split('_')[-1]
    else:
        unix_timestamp = None

    if data['year'] == 'unknown':
        year = None
    else:
        year = data['year']

    if data['view'] == 'unknown':
        view = None
    else:
        view = data['view']

    meta = {'panarama_id_from_url': data.get('panoramaIdFromURL')}

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
