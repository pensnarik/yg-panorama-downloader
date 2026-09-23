#!/usr/bin/env python3
"""HTTP adapter for panorama persistence."""
from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg
from panorama_metadata import CaptureNormalizer
from repository import DatabaseSettings, PanoramaRepository, TileObservation


class MonitoringServer:
    def __init__(self, settings=None):
        self.app = Flask(__name__)
        CORS(self.app)
        self.repository = PanoramaRepository(settings or DatabaseSettings.VALUES)
        self._register_routes()

    def _register_routes(self):
        self.app.add_url_rule('/', view_func=self.index)
        self.app.add_url_rule('/aa/yandex-panorama-metadata', view_func=self.save_metadata, methods=['POST'])
        self.app.add_url_rule('/aa/yandex-panorama-metadata/<image_id>', view_func=self.get_metadata)
        self.app.add_url_rule('/aa/yandex-panorama', view_func=self.observe_yandex, methods=['POST'])
        self.app.add_url_rule('/aa/google-panorama', view_func=self.observe_google, methods=['POST'])

    def save_metadata(self):
        try:
            metadata = CaptureNormalizer.normalize(request.get_json(silent=True))
        except ValueError as error:
            return jsonify(status='error', error=str(error)), 400
        self.repository.save(metadata)
        return jsonify(status='ok', imageId=metadata['imageId'],
                       geometryFieldsPresent=metadata['geometryFieldsPresent'], missingFields=metadata['missingFields'])

    def get_metadata(self, image_id):
        metadata = self.repository.get(image_id)
        if metadata is None:
            return jsonify(status='error', error='Metadata not found'), 404
        return jsonify(metadata)

    def observe_yandex(self):
        self.repository.observe(TileObservation(request.json, 'yandex'))
        return jsonify(status='ok')

    def observe_google(self):
        self.repository.observe(TileObservation(request.json, 'google'))
        return jsonify(status='ok')

    @staticmethod
    def index():
        return 'OK'

    def run(self):
        self.app.run(debug=True)


DB_CONFIG = DatabaseSettings.VALUES
server = MonitoringServer(DB_CONFIG)
app = server.app

if __name__ == '__main__':
    server.run()
