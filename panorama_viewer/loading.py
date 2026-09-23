#!/usr/bin/env python3
"""Bounded, cancellable background decoding without GTK/OpenGL dependencies."""
from dataclasses import dataclass
import queue
import threading
from PIL import Image


@dataclass(frozen=True)
class DecodedPage:
    column: int
    row: int
    width: int
    height: int
    pixels: bytes
    failures: set


class AtlasLoader:
    def __init__(self, panorama, layout):
        self.panorama, self.layout = panorama, layout
        self.messages = queue.Queue(maxsize=3)
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def cancel(self):
        self.cancelled.set()

    def poll(self):
        try:
            return self.messages.get_nowait()
        except queue.Empty:
            return None

    def _send(self, message):
        while not self.cancelled.is_set():
            try:
                self.messages.put(message, timeout=.1)
                return
            except queue.Full:
                pass

    def _run(self):
        try:
            for column, row in self.layout.pages():
                if self.cancelled.is_set():
                    return
                self._send(self.decode(column, row))
        except Exception as error:
            self._send(error)

    def decode(self, column, row):
        width, height = self.layout.output_size(column, row)
        source = self.panorama.level
        region = self.layout.source_region(source.width, source.height, column, row)
        image, failures = self.panorama.read_region(*region)
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        return DecodedPage(column, row, width, height, image.tobytes(), failures)
