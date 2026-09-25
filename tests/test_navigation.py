#!/usr/bin/env python3
"""Saved connections resolve only downloaded panoramas and preserve camera direction."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from panorama_viewer.navigation import PanoramaConnections, LocalPanoramaIndex
from panorama_viewer.navigation_ui import NavigationOverlay


class NavigationTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.panorama = SimpleNamespace(path=self.root / 'metadata.json', panorama_id='current',
                                        data={'Point': {'coordinates': [0, 0, 0]}})

    def links(self, annotation):
        self.panorama.path.write_text(json.dumps({'data': {'Annotation': annotation}}))
        return PanoramaConnections.read(self.panorama)

    def test_graph_only_includes_immediate_neighbors_in_both_directions(self):
        nodes = [{'panoid': name, 'lon': (index - 1) * .001, 'lat': 0} for index, name in enumerate(('west', 'current', 'east', 'far'))]
        links = self.links({'Graph': {'Nodes': nodes, 'Edges': [{'src': 0, 'dst': 1}, {'src': 1, 'dst': 2}, {'src': 2, 'dst': 3}]}})
        self.assertEqual({link.identifier for link in links}, {'west', 'east'})

    def test_road_url_resolves_identifier_without_network(self):
        links = self.links({'Thoroughfares': [{'Direction': [90, 0],
                            'Connection': {'name': 'Лазо', 'href': 'https://example.org/?oid=next'}}]})
        self.assertEqual(links[0].identifier, 'next')
        self.assertEqual(links[0].name, 'Лазо')
        self.assertGreater(links[0].direction[0], .9)

    def test_connection_points_and_self_links(self):
        links = self.links({'Connections': [{'oid': 'next', 'Point': {'coordinates': [.001, 0, 0]}},
                                            {'oid': 'current', 'Point': {'coordinates': [.002, 0, 0]}}]})
        self.assertEqual([link.identifier for link in links], ['next'])

    def test_missing_annotations_have_no_transitions(self):
        self.assertEqual(self.links({}), [])

    def test_index_requires_local_tiles(self):
        paths = [self.manifest('ready', True), self.manifest('missing', False)]
        self.assertEqual(LocalPanoramaIndex.build(paths), {'ready': paths[0]})

    def manifest(self, identifier, tiles):
        path = self.root / identifier / 'metadata.json'
        path.parent.mkdir()
        path.write_text(json.dumps({'data': {'Data': {'panoramaId': identifier}}}))
        if tiles:
            (path.parent / '0').mkdir()
            (path.parent / '0/tile_0_0.jpg').write_bytes(b'tile')
        return path

    def test_click_opens_resolved_path_and_restores_camera(self):
        navigation = NavigationOverlay.__new__(NavigationOverlay)
        navigation.viewer = Mock()
        navigation.viewer.area.camera = SimpleNamespace(yaw=121, pitch=-7, fov=60)
        navigation.index = {'next': self.root / 'next/metadata.json'}
        navigation._navigate(None, 'next')
        navigation.viewer.open_path.assert_called_once_with(navigation.index['next'])
        navigation.viewer.area.set_view.assert_called_once_with(121, -7, 60)

    def test_unavailable_target_does_not_open_anything(self):
        navigation = NavigationOverlay.__new__(NavigationOverlay)
        navigation.viewer, navigation.index = Mock(), {}
        navigation._navigate(None, 'missing')
        navigation.viewer.open_path.assert_not_called()
