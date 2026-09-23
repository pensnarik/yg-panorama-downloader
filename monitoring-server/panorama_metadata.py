"""Versioned offline metadata, retaining every field of the provider response."""

from datetime import datetime
import math
import re
from urllib.parse import urlsplit


def normalize_capture(capture):
    """Validate identity before allowing a response to update an image's metadata."""
    if not isinstance(capture, dict) or capture.get('schemaVersion') != 1:
        raise ValueError('Expected metadata schemaVersion 1')
    if capture.get('provider') != 'yandex':
        raise ValueError('Expected provider yandex')
    raw = capture.get('rawResponse')
    if not isinstance(raw, dict) or raw.get('status') != 'success':
        raise ValueError('Expected a successful Yandex response')
    try:
        data = raw['data']['Data']
        images = data['Images']
        image_id = images['imageId']
        panorama_id = data['panoramaId']
        if not isinstance(image_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', image_id):
            raise ValueError('Invalid imageId')
        if not isinstance(panorama_id, str) or not panorama_id:
            raise ValueError('Missing panoramaId')
        if capture.get('imageId') != image_id or capture.get('panoramaId') != panorama_id:
            raise ValueError('Capture IDs do not match the provider response')
        captured_at = datetime.fromisoformat(capture['capturedAt'].replace('Z', '+00:00'))
        if captured_at.tzinfo is None:
            raise ValueError('capturedAt must include a timezone')
        source = urlsplit(capture['sourceUrl'])
        if (source.scheme != 'https' or source.hostname != 'api-maps.yandex.ru'
                or not source.path.startswith('/services/panoramas/')):
            raise ValueError('Unexpected metadata source URL')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Incomplete metadata envelope') from error

    # Missing/changed geometry is archived too, but never labelled render-ready.
    missing = []
    projection = data.get('EquirectangularProjection')
    origin = projection.get('Origin') if isinstance(projection, dict) else None
    if not (isinstance(origin, list) and len(origin) == 2 and all(
        isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
        for n in origin
    )):
        missing.append('EquirectangularProjection.Origin')

    def positive_int(value):
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    tiles = images.get('Tiles')
    if not (isinstance(tiles, dict) and all(positive_int(tiles.get(k)) for k in ('width', 'height'))):
        missing.append('Images.Tiles')
    zooms = images.get('Zooms')
    if not (isinstance(zooms, list) and zooms and all(
        isinstance(z, dict) and all(positive_int(z.get(k)) for k in ('width', 'height'))
        and isinstance(z.get('level'), int) and not isinstance(z['level'], bool)
        and z['level'] >= 0 for z in zooms
    )):
        missing.append('Images.Zooms')

    return {
        'schemaVersion': 1,
        'provider': 'yandex',
        'imageId': image_id,
        'panoramaId': panorama_id,
        'capturedAt': captured_at.isoformat(),
        'sourceUrl': capture['sourceUrl'],
        'geometryFieldsPresent': not missing,
        'missingFields': missing,
        # Preserve Origin verbatim. Do not guess angularBBox or its conventions.
        'projection': projection,
        'images': images,
        'tileUrlTemplate': f'https://pano.maps.yandex.net/{image_id}/{{level}}.{{x}}.{{y}}',
        'localTileTemplate': f'map/{image_id}/{{level}}/tile_{{x}}_{{y}}.jpg',
        'position': data.get('Point'),
        'timestamp': data.get('timestamp'),
        'defaultView': data.get('View'),
        'rawResponse': raw,
    }
