#!/usr/bin/env python3

import os
import sys
import psycopg

from psycopg.rows import dict_row

from PIL import Image, ImageDraw, ImageFont, ImageFilter


# Параметры подключения к базе данных
DB_CONFIG = {
    "dbname": "allarchive",
    "user": "allarchive",
    "password": "allarchive",
    "host": "localhost",
    "port": 5432
}

class App():

    def __init__(self):
        self.loc = sys.argv[1]
        self.zoom_level = int(sys.argv[2])

        if len(self.loc) > 12:
            self.provider = 'google'
        else:
            self.provider = 'yandex'

    def get_title(self, panorama_id: str, provider: str):
        query = "select external_id, lat, lon, " \
                "       (case when unix_timestamp is not null then to_timestamp(unix_timestamp) at time zone 'UTC' else null end)::text as unix_timestamp, " \
                "       coalesce(unix_timestamp::text, year::text, time_info) as date, " \
                "       view_name, " \
                "       count(*) " \
                "  from aa.panorama_log " \
                " where external_id = %s " \
                "   and provider = %s " \
                " group by 1, 2, 3, 4, 5, 6 " \
                " order by count(*) desc limit 1"

        with psycopg.connect(**DB_CONFIG) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, [panorama_id, provider])

                result = cursor.fetchone()

                if result is None:
                    raise Exception(f"Could not find {panorama_id} in the DB")

                if result['view_name']:
                    return f"{result['unix_timestamp'] or result['date']}, " \
                           f"{result['lat']},{result['lon']} | " \
                           f"{result['view_name']}"
                else:
                    return f"{result['unix_timestamp'] or result['date']}, " \
                           f"{result['lat']},{result['lon']}"


    def text_with_shadow(self, image: Image, draw: ImageDraw.Draw, text: str):
        font = ImageFont.truetype("font.ttf", size=80)

        # Параметры тени (аналогично text-shadow: 0 1px 2px #000)
        shadow_color = "#000000"  # Черный цвет тени
        shadow_offset = (0, 1)    # Смещение тени (x, y)
        blur_radius = 2           # Радиус размытия

        # Создаем отдельное изображение для тени
        shadow_image = Image.new("RGBA", (image.width, image.height), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_image)

        # Рисуем тень с учетом смещения
        shadow_draw.text(
            (10 + shadow_offset[0], 10 + shadow_offset[1]),
            text,
            font=font,
            fill=shadow_color,
        )

        # Применяем размытие к тени
        shadow_image = shadow_image.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        # Накладываем тень на основное изображение
        image.paste(shadow_image, mask=shadow_image)

        # Рисуем основной текст
        draw.text((10,10), text, font=font, fill="white")


    def __get_tile_size(self):
        if self.provider == 'google':
            return 512
        else:
            return 256


    def __get_tile_files(self, tiles_dir: str) -> list:
        # Получаем список всех файлов тайлов
        tile_files = [f for f in os.listdir(tiles_dir) if f.startswith("tile_") and f.endswith(".jpg")]

        if not tile_files:
            raise Exception(f"No tiles found in {tiles_dir}")

        return tile_files

    def __get_rows_and_cols(self, tile_files: list) -> tuple:
        # Определяем количество строк и столбцов
        rows = set()
        cols = set()

        for tile_file in tile_files:
            # Извлекаем номер строки и столбца из имени файла
            parts = tile_file.split("_")
            col = int(parts[1])
            row = int(parts[2].split(".")[0])
            rows.add(row)
            cols.add(col)

        return len(rows), len(cols)


    def merge_tiles(
        self,
        image: Image,
        draw: ImageDraw.Draw,
        num_rows: int,
        num_cols: int,
        tile_size: int
    ):
        # Склеиваем тайлы
        for row in range(0, num_rows):
            for col in range(0, num_cols):

                tile_filename = f"./map/{self.loc}/{self.zoom_level}/tile_{col}_{row}.jpg"
                # Вычисляем позицию тайла на панораме
                x = col * tile_size
                y = row * tile_size

                if os.path.exists(tile_filename):
                    # Открываем тайл
                    tile = Image.open(tile_filename)

                    if tile.size != (tile_size, tile_size):
                        tile = tile.resize((tile_size, tile_size), Image.Resampling.LANCZOS)

                    # Вставляем тайл в панораму
                    image.paste(tile, (x, y))
                    #draw.text((x * tile_size + 10, y * tile_size + 10), f"{col}_{row}", font=font, fill="red")
                    #print(f"{x=},{y=}")
                else:
                    # Рисуем зелёный квадрат
                    draw.rectangle((x * tile_size, y * tile_size, (x + 1) * tile_size, (y + 1) * tile_size), fill="green")
                    # Добавляем текст с информацией об отсутствующем тайле
                    # draw.text((x * tile_size + 10, y * tile_size + 10), f"Missing: {tile_filename}", font=font, fill="red")


    def run(self):
        # Путь к директории с тайлами
        tiles_dir = f"./map/{self.loc}/{self.zoom_level}"

        tile_files = self.__get_tile_files(tiles_dir)
        tile_size = self.__get_tile_size()

        text = self.get_title(self.loc, self.provider)

        num_rows, num_cols = self.__get_rows_and_cols(tile_files)

        print(f"{num_rows=}, {num_cols=}")

        # Рассчитываем итоговый размер панорамы
        panorama_width = num_cols * tile_size
        panorama_height = num_rows * tile_size

        print(f"{panorama_width=}, {panorama_height}")

        # Создаём пустое изображение для панорамы
        panorama = Image.new("RGB", (panorama_width, panorama_height))
        draw = ImageDraw.Draw(panorama)

        self.merge_tiles(panorama, draw, num_rows, num_cols, tile_size)

        self.text_with_shadow(panorama, draw, text)

        # Сохраняем панораму
        output_path = os.path.join(f"./panos", f"{self.loc}.jpg")
        panorama.save(output_path)
        print(f"Panorama saved into {output_path}")


if __name__ == '__main__':
    sys.exit(App().run())
