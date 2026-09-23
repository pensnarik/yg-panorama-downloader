#!/usr/bin/env python3
"""CLI parsing and application selection."""
import argparse
import math
from pathlib import Path
import sys


class ViewerArguments:
    OPTIONS = (
        ('source', {'nargs': '?', 'help': 'metadata.json или каталог панорамы'}),
        ('--library', {'default': str(Path(__file__).resolve().parents[1] / 'map'), 'help': 'Каталог панорам'}),
        ('--level', {'type': int, 'help': 'Уровень тайлов (автоматически: лучший полный)'}),
        ('--yaw', {'type': float, 'help': 'Азимут в градусах (север = 0)'}),
        ('--pitch', {'type': float, 'help': 'Наклон вверх в градусах'}),
        ('--fov', {'type': float, 'help': 'Вертикальный обзор, 15–110°'}),
        ('--gpu-memory', {'type': int, 'default': 768, 'metavar': 'MiB'}),
        ('--render', {'metavar': 'PNG', 'help': 'Сохранить вид без GTK/GPU'}),
        ('--globe', {'metavar': 'PDF', 'help': 'Развёртка для наклейки на шар, A4, масштаб 1:1'}),
        ('--globe-diameter', {'type': float, 'default': 100, 'metavar': 'MM'}),
        ('--globe-gores', {'type': int, 'default': 24, 'metavar': 'N'}),
        ('--globe-dpi', {'type': int, 'default': 300, 'metavar': 'DPI'}),
        ('--width', {'type': int, 'default': 1000}),
        ('--height', {'type': int, 'default': 700}),
        ('--smoke-test', {'metavar': 'PNG', 'help': argparse.SUPPRESS}),
    )

    def __init__(self):
        self.parser = argparse.ArgumentParser(description='Офлайн-просмотр панорам Яндекса (GTK4/OpenGL).')
        for name, settings in self.OPTIONS:
            self.parser.add_argument(name, **settings)

    def parse(self, arguments=None):
        options = self.parser.parse_args(arguments)
        self._validate_angles(options)
        self._validate_ranges(options)
        self._validate_exports(options)
        return options

    def _validate_exports(self, options):
        from .globe import GlobeSettings
        if sum(bool(value) for value in (options.render, options.globe, options.smoke_test)) > 1:
            self.parser.error('--render, --globe и --smoke-test нельзя использовать вместе')
        if (options.render or options.globe) and not options.source:
            self.parser.error('Для экспорта укажите metadata.json или каталог панорамы')
        try:
            GlobeSettings(options.globe_diameter, options.globe_gores, options.globe_dpi, options.yaw or 0)
        except ValueError as error:
            self.parser.error(str(error))

    def _validate_angles(self, options):
        for name in ('yaw', 'pitch', 'fov'):
            value = getattr(options, name)
            if value is not None and not math.isfinite(value):
                self.parser.error(f'--{name} должен быть конечным числом')

    def _validate_ranges(self, options):
        for valid, message in self._range_checks(options):
            if not valid:
                self.parser.error(message)

    @staticmethod
    def _range_checks(options):
        return (
            (16 <= options.gpu_memory <= 8192, '--gpu-memory должен быть от 16 до 8192 MiB'),
            (options.fov is None or 15 <= options.fov <= 110, '--fov должен быть от 15 до 110'),
            (options.pitch is None or -89.9 <= options.pitch <= 89.9, '--pitch должен быть от -89.9 до 89.9'),
            (1 <= options.width <= 8192 and 1 <= options.height <= 8192, 'Размер снимка: 1–8192 по стороне'),
            (options.width * options.height <= 16_000_000, 'Размер снимка: до 16 Мп суммарно'),
        )


class ViewerCommand:
    @classmethod
    def run(cls, arguments=None):
        options = ViewerArguments().parse(arguments)
        try:
            return cls._dispatch(options)
        except ImportError as error:
            return cls._error(f'Не найдена библиотека: {error}. Зависимости описаны в README.')
        except (OSError, ValueError, KeyError, TypeError) as error:
            return cls._error(f'Не удалось открыть панораму: {error}')

    @staticmethod
    def _error(message):
        print(message, file=sys.stderr)
        return 1

    @classmethod
    def _dispatch(cls, options):
        if options.globe:
            return cls._globe(options)
        return cls._render(options) if options.render else cls._open_window(options)

    @staticmethod
    def _globe(options):
        from .model import Panorama
        from .globe import GlobeSettings
        from .globe_pdf import GlobePdf
        settings = GlobeSettings(options.globe_diameter, options.globe_gores, options.globe_dpi, options.yaw or 0)
        path = GlobePdf(Panorama(options.source, options.level), settings).save(options.globe)
        print(f'Сохранено: {path}. Печатайте в масштабе 100%, без подгонки к странице.')
        return 0

    @classmethod
    def _render(cls, options):
        from .model import Panorama
        from .projection import CpuRenderer
        panorama = Panorama(options.source, options.level)
        image = CpuRenderer.render(panorama, options.width, options.height, *cls._view(options, panorama))
        image.save(options.render, format='PNG')
        print(f'Сохранено: {options.render}')
        return 0

    @staticmethod
    def _view(options, panorama):
        return (panorama.default_yaw if options.yaw is None else options.yaw,
                panorama.default_pitch if options.pitch is None else options.pitch,
                max(15, min(110, panorama.default_fov)) if options.fov is None else options.fov)

    @classmethod
    def _open_window(cls, options):
        from .app import Viewer
        application = Viewer(options)
        result = application.run([sys.argv[0]])
        return cls._error(application.smoke_error) if application.smoke_error else result
