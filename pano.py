#!/usr/bin/env python3
"""Download Yandex panorama tiles."""
from panorama_archive.download import DownloadCommand

if __name__ == '__main__':
    raise SystemExit(DownloadCommand.run('yandex'))
