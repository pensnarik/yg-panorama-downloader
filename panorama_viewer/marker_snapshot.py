#!/usr/bin/env python3
"""Include visible offline marker labels in exported viewer snapshots."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


class MarkerSnapshot:
    @classmethod
    def save(cls, path, entries, viewport_width):
        if not entries or viewport_width <= 0:
            return
        with Image.open(path) as source:
            image = source.convert('RGB')
        scale = image.width / viewport_width
        font = ImageFont.truetype(str(Path(__file__).resolve().parents[1] / 'font.ttf'), max(1, round(14 * scale)))
        for rectangle, marker in entries:
            cls._label(ImageDraw.Draw(image), rectangle, marker.name, font, scale)
        image.save(path, format='PNG')

    @staticmethod
    def _label(draw, rectangle, text, font, scale):
        left, top, width, height = [value * scale for value in rectangle]
        draw.rounded_rectangle((left, top, left + width, top + height), radius=8 * scale,
                               fill='#18202c', outline='white', width=max(1, round(scale)))
        while len(text) > 1 and draw.textlength(text, font=font) > width - 12 * scale:
            text = text[:-2] + '…'
        bounds = draw.textbbox((0, 0), text, font=font)
        position = (left + (width - bounds[2] + bounds[0]) / 2 - bounds[0],
                    top + (height - bounds[3] + bounds[1]) / 2 - bounds[1])
        draw.text(position, text, font=font, fill='white')
