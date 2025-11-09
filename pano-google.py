#!/usr/bin/env python3

import os
import sys

import requests

loc = sys.argv[1]
zoom_level = int(sys.argv[2])

base_url = f"https://streetviewpixels-pa.googleapis.com/v1/tile?" \
           f"cb_client=maps_sv.tactile&panoid={loc}"

if not os.path.exists(f"./map/{loc}/{zoom_level}"):
    os.makedirs(f"./map/{loc}/{zoom_level}")

RANGES = {
    # zoom cols rows
    4: (range(0, 10), range(0, 10)),
    5: (range(0, 26), range(0, 13))
}

print(f"Downloading {loc}")

stop_outer_loop = False

for col in RANGES[zoom_level][0]:
    if stop_outer_loop:
        break

    for row in RANGES[zoom_level][1]:
        url = f"{base_url}&x={col}&y={row}&zoom={zoom_level}&nbt=1&fover=2"

        if os.path.exists(f"./map/{loc}/{zoom_level}/tile_{col}_{row}.jpg"):
            print(f"tile_{row}_{col}.jpg exists")
            continue

        response = requests.get(url)

        if response.status_code == 200:
            with open(f"./map/{loc}/{zoom_level}/tile_{col}_{row}.jpg", "wb") as f:
                f.write(response.content)
            print(f"Downloaded: {url}")
        elif response.status_code == 400:
            if row == 0:
                stop_outer_loop = True
            break
        else:
            print(f"Could not download: {url}, {response.status_code=}")
