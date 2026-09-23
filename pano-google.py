#!/usr/bin/env python3
"""Download Google panorama tiles."""
from panorama_archive.download import DownloadCommand

if __name__ == '__main__':
    raise SystemExit(DownloadCommand.run('google'))
