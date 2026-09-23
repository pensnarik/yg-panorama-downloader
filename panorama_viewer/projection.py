"""Exact ray-to-equirectangular projection and a CPU reference renderer."""
import math
import numpy as np
from PIL import Image
from .model import missing_pattern


def camera_basis(yaw, pitch):
    yaw, pitch = math.radians(yaw), math.radians(pitch)
    right = np.array([math.cos(yaw), 0, -math.sin(yaw)], dtype=np.float32)
    up = np.array([-math.sin(yaw) * math.sin(pitch), math.cos(pitch),
                   -math.cos(yaw) * math.sin(pitch)], dtype=np.float32)
    forward = np.array([math.sin(yaw) * math.cos(pitch), math.sin(pitch),
                        math.cos(yaw) * math.cos(pitch)], dtype=np.float32)
    return right, up, forward


def pixel_coordinates(panorama, width, height, yaw, pitch, fov):
    right, up, forward = camera_basis(yaw, pitch)
    y, x = np.mgrid[:height, :width].astype(np.float32)
    scale = math.tan(math.radians(fov) / 2)
    x = (2 * (x + .5) / width - 1) * (width / height) * scale
    y = (1 - 2 * (y + .5) / height) * scale
    ray = forward + x[..., None] * right + y[..., None] * up
    ray /= np.linalg.norm(ray, axis=-1)[..., None]
    phi = np.arctan2(ray[..., 0], ray[..., 2])
    theta = np.arcsin(np.clip(ray[..., 1], -1, 1))
    u = ((phi - panorama.azimuth_origin) / (2 * math.pi)) % 1
    v = (panorama.top - theta) / panorama.span
    return u * panorama.level.width - .5, v * panorama.level.height - .5, (v >= 0) & (v <= 1)


def render_cpu(panorama, width=1000, height=700, yaw=0, pitch=0, fov=60):
    """Sample only the tiles needed for this view, at their native resolution."""
    x, y, valid = pixel_coordinates(panorama, width, height, yaw, pitch, fov)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    cache = {}

    def sample(px, py):
        px = px % panorama.level.width
        py = np.clip(py, 0, panorama.level.height - 1)
        tx, ty = px // panorama.tile_width, py // panorama.tile_height
        result = np.empty((height, width, 3), dtype=np.float32)
        columns = math.ceil(panorama.level.width / panorama.tile_width)
        ids = ty * columns + tx
        for tile_id in np.unique(ids):
            row, col = divmod(int(tile_id), columns)
            if tile_id not in cache:
                image, _ = panorama.read_region(col * panorama.tile_width, row * panorama.tile_height,
                                               panorama.tile_width, panorama.tile_height)
                cache[tile_id] = np.asarray(image)
            mask = ids == tile_id
            result[mask] = cache[tile_id][py[mask] % panorama.tile_height, px[mask] % panorama.tile_width]
        return result

    output = ((1 - fy)[..., None] * ((1 - fx)[..., None] * sample(x0, y0) + fx[..., None] * sample(x0 + 1, y0))
              + fy[..., None] * ((1 - fx)[..., None] * sample(x0, y0 + 1) + fx[..., None] * sample(x0 + 1, y0 + 1)))
    output[~valid] = (17, 22, 29)
    return Image.fromarray(np.clip(output, 0, 255).astype(np.uint8))
