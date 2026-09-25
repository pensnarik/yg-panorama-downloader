#!/usr/bin/env python3
"""Resolve saved panorama connections without fetching provider URLs."""
from dataclasses import dataclass
import json
import math
from urllib.parse import urlsplit, parse_qs
import numpy as np
from .markers import MarkerGeometry


@dataclass(frozen=True)
class PanoramaLink:
    identifier: str
    name: str
    direction: np.ndarray


class PanoramaConnections:
    @classmethod
    def read(cls, panorama):
        annotation = cls._annotation(panorama)
        links = cls._graph(annotation.get('Graph') or {}, panorama)
        for item in annotation.get('Thoroughfares') or []:
            link = cls._road(item)
            if link and link.identifier != panorama.panorama_id:
                links[link.identifier] = link
        cls._connections(annotation, panorama, links)
        return list(links.values())

    @staticmethod
    def _annotation(panorama):
        try:
            payload = json.loads(panorama.path.read_text())
            raw = payload.get('rawResponse', payload).get('data', {})
            annotation = raw.get('Annotation') or {}
            return annotation if isinstance(annotation, dict) else {}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    @classmethod
    def _connections(cls, annotation, panorama, links):
        for item in annotation.get('Connections') or []:
            try:
                coordinates = item['Point']['coordinates']
                node = {'lon': coordinates[0], 'lat': coordinates[1], 'panoid': cls._identifier(item)}
                link = cls._node(node, panorama)
                if link and link.identifier != panorama.panorama_id:
                    links.setdefault(link.identifier, link)
            except (TypeError, KeyError, IndexError, AttributeError, ValueError):
                continue

    @classmethod
    def _graph(cls, graph, panorama):
        nodes = graph.get('Nodes') or []
        current = next((index for index, node in enumerate(nodes) if node.get('panoid') == panorama.panorama_id), None)
        neighbors = cls._neighbors(graph.get('Edges') or [], current)
        links = [cls._node(nodes[index], panorama) for index in neighbors if 0 <= index < len(nodes)]
        return {link.identifier: link for link in links if link}

    @staticmethod
    def _neighbors(edges, current):
        result = set()
        for edge in edges if current is not None else []:
            source, target = edge.get('src'), edge.get('dst')
            other = target if source == current else source if target == current else None
            if isinstance(other, int) and other != current:
                result.add(other)
        return sorted(result)

    @classmethod
    def _node(cls, node, panorama):
        try:
            vector, distance = MarkerGeometry.direction(panorama.data['Point']['coordinates'], [node['lon'], node['lat']])
            azimuth = math.degrees(math.atan2(vector[0], vector[2]))
            identifier = node.get('panoid') or cls._identifier(node)
            return PanoramaLink(identifier, 'Соседняя панорама', cls._direction(azimuth)) if identifier else None
        except (ValueError, TypeError, KeyError, IndexError):
            return None

    @classmethod
    def _road(cls, item):
        try:
            connection = item['Connection']
            identifier = cls._identifier(connection)
            azimuth = float(item['Direction'][0])
            if not identifier or not math.isfinite(azimuth):
                return None
            return PanoramaLink(identifier, str(connection.get('name') or 'Соседняя панорама'), cls._direction(azimuth))
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            return None

    @staticmethod
    def _identifier(connection):
        return connection.get('oid') or parse_qs(urlsplit(connection.get('href', '')).query).get('oid', [None])[0]

    @staticmethod
    def _direction(azimuth):
        azimuth, pitch = math.radians(azimuth), math.radians(-12)
        return np.array([math.sin(azimuth) * math.cos(pitch), math.sin(pitch), math.cos(azimuth) * math.cos(pitch)])


class LocalPanoramaIndex:
    @classmethod
    def build(cls, paths):
        result = {}
        for path in paths:
            identifier = cls._identifier(path)
            if identifier:
                result[identifier] = path
        return result

    @staticmethod
    def _identifier(path):
        from .model import MetadataValues
        try:
            data = MetadataValues.read(path)
            if not (path.parent / '.download-in-progress').exists() and any(path.parent.glob('*/tile_*_*.jpg')):
                return data.get('panoramaId')
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None
