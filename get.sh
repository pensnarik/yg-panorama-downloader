#!/usr/bin/env bash

PANORAMA_ID=$1
ZOOM_LEVEL="0"

./pano.py "${PANORAMA_ID}" "${ZOOM_LEVEL}"
./merge.py "${PANORAMA_ID}" "${ZOOM_LEVEL}"
