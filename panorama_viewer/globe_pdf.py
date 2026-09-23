#!/usr/bin/env python3
"""A4 output at exact physical dimensions, independent of GTK and OpenGL."""
import math
from pathlib import Path
import tempfile
import numpy as np
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from .globe import GlobeLayout, GoreProjection, GoreRenderer


class GlobePdf:
    def __init__(self, panorama, settings):
        self.panorama = panorama
        self.settings = settings
        self.layout = GlobeLayout(settings)
        self.renderer = GoreRenderer(panorama, settings)

    def save(self, destination):
        destination = Path(destination).expanduser().resolve()
        if destination.suffix.lower() != '.pdf':
            raise ValueError('Для развёртки укажите файл с расширением .pdf')
        with tempfile.TemporaryDirectory(prefix='.globe-', dir=destination.parent) as directory:
            temporary = Path(directory) / 'globe.pdf'
            self._write(temporary)
            temporary.replace(destination)
        return destination

    def _write(self, destination):
        self._register_font()
        self.canvas = Canvas(str(destination), pagesize=tuple(value * mm for value in self.layout.page_size))
        self.canvas.setTitle(f'Panorama globe - {self.panorama.image_id}')
        self.canvas.setAuthor('Panorama viewer')
        for page in range(self.layout.pages):
            self._page(page)
            self.canvas.showPage()
        self.canvas.save()

    @staticmethod
    def _register_font():
        if 'PanoramaPrint' not in pdfmetrics.getRegisteredFontNames():
            font = Path(__file__).resolve().parents[1] / 'font.ttf'
            pdfmetrics.registerFont(TTFont('PanoramaPrint', str(font)))

    def _page(self, page):
        self._heading(page)
        for index in self.layout.indices(page):
            center = self.layout.center(page, index)
            self._image(center, index)
            self._outline(center)
            self._label(center, index)
        self._footer()

    def _heading(self, page):
        width, height = self.layout.page_size
        self.canvas.setFont('PanoramaPrint', 12)
        self.canvas.drawString(10 * mm, (height - 12) * mm, 'ПАНОРАМА НА ШАРЕ')
        self.canvas.setFont('PanoramaPrint', 9)
        self.canvas.drawRightString((width - 10) * mm, (height - 12) * mm, f'{page + 1} / {self.layout.pages}')
        settings = self.settings
        detail = f'Диаметр {settings.diameter:g} мм | Лепестков: {settings.gores} | {settings.dpi} DPI | A4 | Масштаб 100%'
        self.canvas.drawString(10 * mm, (height - 18) * mm, detail)

    def _image(self, center, index):
        settings = self.settings
        image = self.renderer.render(index)
        self.canvas.drawImage(ImageReader(image), (center - settings.width / 2) * mm, self.layout.BOTTOM * mm,
                              width=settings.width * mm, height=settings.height * mm)

    def _outline(self, center):
        path = self.canvas.beginPath()
        self._edge(path, center, -1, np.linspace(math.pi / 2, -math.pi / 2, 181), True)
        self._edge(path, center, 1, np.linspace(-math.pi / 2, math.pi / 2, 181), False)
        path.close()
        self.canvas.setStrokeColorRGB(.35, .35, .35)
        self.canvas.setLineWidth(.15)
        self.canvas.drawPath(path)

    def _edge(self, path, center, side, latitudes, first):
        for latitude in latitudes:
            horizontal = center + side * GoreProjection.half_width(self.settings, latitude)
            vertical = self.layout.BOTTOM + self.settings.radius * (latitude + math.pi / 2)
            operation = path.moveTo if first else path.lineTo
            operation(horizontal * mm, vertical * mm)
            first = False

    def _label(self, center, index):
        self.canvas.setFont('PanoramaPrint', 8)
        self.canvas.drawCentredString(center * mm, 21 * mm, f'{index + 1:02d}')
        self.canvas.setFont('PanoramaPrint', 6)
        azimuth = math.degrees(self.settings.center(index)) % 360
        self.canvas.drawCentredString(center * mm, 18 * mm, f'{azimuth:.0f}°')
        self._equator_ticks(center)

    def _equator_ticks(self, center):
        vertical = (self.layout.BOTTOM + self.settings.height / 2) * mm
        for side in (-1, 1):
            edge = center + side * self.settings.width / 2
            self.canvas.line((edge + side * .4) * mm, vertical, (edge + side * 1.3) * mm, vertical)

    def _footer(self):
        self.canvas.setFont('PanoramaPrint', 7)
        self.canvas.drawString(10 * mm, 12 * mm, 'Верх: зенит. Склейка встык: 01 -> 02 -> ... -> 01. Без клапанов.')
        self.canvas.drawString(10 * mm, 8 * mm, 'Серое: нет съёмки. Клетки: нет тайлов. Печать без подгонки к листу.')
        self._ruler()

    def _ruler(self):
        right = self.layout.page_size[0] - 10
        self.canvas.setStrokeColorRGB(0, 0, 0)
        self.canvas.setLineWidth(.5)
        self.canvas.line((right - 50) * mm, 8 * mm, right * mm, 8 * mm)
        for horizontal in (right - 50, right):
            self.canvas.line(horizontal * mm, 7 * mm, horizontal * mm, 9 * mm)
        self.canvas.drawCentredString((right - 25) * mm, 11 * mm, 'ПРОВЕРКА: 50 мм')
