#!/usr/bin/env python3

import os
import sys
import time
import requests

loc = sys.argv[1]
zoom_level = int(sys.argv[2])

base_url = f"https://pano.maps.yandex.net/{loc}"

if not os.path.exists(f"./map/{loc}/{zoom_level}"):
    os.makedirs(f"./map/{loc}/{zoom_level}")

RANGES = {
    # zoom cols rows
    1: (range(0, 28), range(0, 14)),
    0: (range(0, 74), range(0, 29))
}

stop_outer_loop = False

print(f"Downloading {loc}")

for col in RANGES[zoom_level][0]:
    if stop_outer_loop:
        break

    for row in RANGES[zoom_level][1]:
        url = f"{base_url}/{zoom_level}.{col}.{row}"

        if os.path.exists(f"./map/{loc}/{zoom_level}/tile_{col}_{row}.jpg"):
            print(f"tile_{row}_{col}.jpg exists")
            continue

        response = requests.get(url)

        if response.status_code == 200:
            with open(f"./map/{loc}/{zoom_level}/tile_{col}_{row}.jpg", "wb") as f:
                f.write(response.content)
            print(f"Downloaded: {url}")
        elif response.status_code == 404:
            # If a tile is not found, consider we have reached maximum
            # row number for
            if row == 0:
                stop_outer_loop = True
            break
        else:
            print(f"Could not download: {url}, {response.status_code=}")
