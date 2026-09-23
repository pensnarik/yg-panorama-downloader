#!/usr/bin/env python3
"""Offline panorama viewer: Python + GTK4 + OpenGL 3.3."""
import argparse
import math
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description='Офлайн-просмотр панорам Яндекса (GTK4/OpenGL).')
    parser.add_argument('source', nargs='?', help='metadata.json или каталог панорамы')
    parser.add_argument('--library', default=str(Path(__file__).resolve().parent / 'map'), help='Каталог локальных панорам')
    parser.add_argument('--level', type=int, help='Уровень тайлов; автоматически выбирается лучший полный уровень')
    parser.add_argument('--yaw', type=float, help='Азимут в градусах (север = 0)')
    parser.add_argument('--pitch', type=float, help='Наклон в градусах (вверх положительный)')
    parser.add_argument('--fov', type=float, help='Вертикальный угол обзора, 15–110°')
    parser.add_argument('--gpu-memory', type=int, default=768, metavar='MiB', help='Бюджет текстуры; по умолчанию 768 MiB')
    parser.add_argument('--render', metavar='PNG', help='Сохранить вид без GTK и GPU (исходное разрешение тайлов)')
    parser.add_argument('--width', type=int, default=1000, help='Ширина --render, по умолчанию 1000')
    parser.add_argument('--height', type=int, default=700, help='Высота --render, по умолчанию 700')
    parser.add_argument('--smoke-test', metavar='PNG', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.gpu_memory < 16 or args.gpu_memory > 8192:
        parser.error('--gpu-memory должен быть от 16 до 8192 MiB')
    for name in ('yaw', 'pitch', 'fov'):
        value = getattr(args, name)
        if value is not None and not math.isfinite(value):
            parser.error(f'--{name} должен быть конечным числом')
    if args.fov is not None and not 15 <= args.fov <= 110:
        parser.error('--fov должен быть от 15 до 110')
    if args.pitch is not None and not -89.9 <= args.pitch <= 89.9:
        parser.error('--pitch должен быть от -89.9 до 89.9')
    if not 1 <= args.width <= 8192 or not 1 <= args.height <= 8192 or args.width*args.height > 16_000_000:
        parser.error('Размер снимка должен быть до 8192 по стороне и 16 Мп суммарно')
    try:
        if args.render:
            from panorama_viewer.model import Panorama
            from panorama_viewer.projection import render_cpu
            if not args.source:
                parser.error('Для --render укажите metadata.json или каталог панорамы')
            p = Panorama(args.source, args.level)
            image = render_cpu(p, args.width, args.height,
                               p.default_yaw if args.yaw is None else args.yaw,
                               p.default_pitch if args.pitch is None else args.pitch,
                               max(15, min(110, p.default_fov)) if args.fov is None else args.fov)
            image.save(args.render, format='PNG')
            print(f'Сохранено: {args.render}')
            return 0
        from panorama_viewer.app import Viewer
        app = Viewer(args)
        result = app.run([sys.argv[0]])
        if app.smoke_error:
            print(app.smoke_error, file=sys.stderr)
            return 1
        return result
    except ImportError as error:
        print(f'Не найдена библиотека: {error}. Запустите /usr/bin/python3 viewer.py; зависимости описаны в README.', file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Не удалось открыть панораму: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
