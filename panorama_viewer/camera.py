#!/usr/bin/env python3
"""Camera state and gesture mathematics."""
from dataclasses import dataclass
import math


@dataclass
class Camera:
    yaw: float = 0.
    pitch: float = 0.
    fov: float = 60.

    def set_view(self, yaw=None, pitch=None, fov=None):
        if yaw is not None:
            self.yaw = yaw % 360
        if pitch is not None:
            self.pitch = max(-89.9, min(89.9, pitch))
        if fov is not None:
            self.fov = max(15., min(110., fov))

    def begin_drag(self):
        self.drag_origin = self.yaw, self.pitch

    def drag(self, horizontal, vertical, viewport_height):
        scale = 2 * math.tan(math.radians(self.fov) / 2) / max(1, viewport_height)
        self.set_view(self.drag_origin[0] - math.degrees(math.atan(horizontal * scale)),
                      self.drag_origin[1] + math.degrees(math.atan(vertical * scale)))

    def scroll(self, distance):
        self.set_view(fov=self.fov * math.exp(max(-2, min(2, distance)) * .09))
