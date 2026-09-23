#!/usr/bin/env python3
"""Exact ray projection and independent CPU renderer."""
import math
import numpy as np
from PIL import Image


class SphericalProjection:
    @staticmethod
    def camera_basis(yaw, pitch):
        yaw, pitch = math.radians(yaw), math.radians(pitch)
        right = np.array([math.cos(yaw), 0, -math.sin(yaw)], dtype=np.float32)
        up = np.array([-math.sin(yaw)*math.sin(pitch), math.cos(pitch),
                       -math.cos(yaw)*math.sin(pitch)], dtype=np.float32)
        forward = np.array([math.sin(yaw)*math.cos(pitch), math.sin(pitch),
                            math.cos(yaw)*math.cos(pitch)], dtype=np.float32)
        return right, up, forward

    @staticmethod
    def screen_coordinates(width, height, fov):
        rows, columns = np.mgrid[:height, :width].astype(np.float32)
        scale = math.tan(math.radians(fov) / 2)
        horizontal = (2 * (columns + .5) / width - 1) * (width / height) * scale
        vertical = (1 - 2 * (rows + .5) / height) * scale
        return horizontal, vertical

    @classmethod
    def rays(cls, width, height, yaw, pitch, fov):
        right, up, forward = cls.camera_basis(yaw, pitch)
        horizontal, vertical = cls.screen_coordinates(width, height, fov)
        rays = forward + horizontal[..., None] * right + vertical[..., None] * up
        return rays / np.linalg.norm(rays, axis=-1)[..., None]

    @classmethod
    def pixel_coordinates(cls, panorama, width, height, yaw, pitch, fov):
        rays = cls.rays(width, height, yaw, pitch, fov)
        azimuth = np.arctan2(rays[..., 0], rays[..., 2])
        latitude = np.arcsin(np.clip(rays[..., 1], -1, 1))
        horizontal = ((azimuth - panorama.azimuth_origin) / (2 * math.pi)) % 1
        vertical = (panorama.top - latitude) / panorama.span
        return (horizontal * panorama.level.width - .5, vertical * panorama.level.height - .5,
                (vertical >= 0) & (vertical <= 1))


class TileSampler:
    def __init__(self, panorama):
        self.panorama = panorama
        self.cache = {}
        self.columns = math.ceil(panorama.level.width / panorama.tile_width)

    def _tile(self, tile_id):
        if tile_id not in self.cache:
            row, column = divmod(int(tile_id), self.columns)
            width, height = self.panorama.tile_width, self.panorama.tile_height
            image, _ = self.panorama.read_region(column*width, row*height, width, height)
            self.cache[tile_id] = np.asarray(image)
        return self.cache[tile_id]

    def sample(self, horizontal, vertical):
        horizontal = horizontal % self.panorama.level.width
        vertical = np.clip(vertical, 0, self.panorama.level.height - 1)
        columns, rows = horizontal // self.panorama.tile_width, vertical // self.panorama.tile_height
        tile_ids = rows * self.columns + columns
        result = np.empty((*horizontal.shape, 3), dtype=np.float32)
        for tile_id in np.unique(tile_ids):
            mask = tile_ids == tile_id
            result[mask] = self._samples_in_tile(tile_id, horizontal[mask], vertical[mask])
        return result

    def _samples_in_tile(self, tile_id, horizontal, vertical):
        return self._tile(tile_id)[vertical % self.panorama.tile_height, horizontal % self.panorama.tile_width]

    def interpolate(self, horizontal, vertical):
        left, top = np.floor(horizontal).astype(int), np.floor(vertical).astype(int)
        fraction_x, fraction_y = horizontal - left, vertical - top
        upper = self._mix(self.sample(left, top), self.sample(left + 1, top), fraction_x)
        lower = self._mix(self.sample(left, top + 1), self.sample(left + 1, top + 1), fraction_x)
        return self._mix(upper, lower, fraction_y)

    @staticmethod
    def _mix(first, second, fraction):
        return (1 - fraction)[..., None] * first + fraction[..., None] * second


class CpuRenderer:
    @staticmethod
    def render(panorama, width=1000, height=700, yaw=0, pitch=0, fov=60):
        horizontal, vertical, valid = SphericalProjection.pixel_coordinates(panorama, width, height, yaw, pitch, fov)
        output = TileSampler(panorama).interpolate(horizontal, vertical)
        output[~valid] = (17, 22, 29)
        return Image.fromarray(np.clip(output, 0, 255).astype(np.uint8))


camera_basis = SphericalProjection.camera_basis
pixel_coordinates = SphericalProjection.pixel_coordinates
render_cpu = CpuRenderer.render
