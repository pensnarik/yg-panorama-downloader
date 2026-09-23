#!/usr/bin/env python3
"""Monitor the database and download newly discovered panoramas."""
from panorama_archive.monitor import DownloadMonitor

App = DownloadMonitor

if __name__ == '__main__':
    App().run()
