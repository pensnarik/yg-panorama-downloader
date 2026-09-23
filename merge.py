#!/usr/bin/env python3
"""Merge downloaded tiles into a captioned flat image."""
from panorama_archive.merge import MergeApplication

App = MergeApplication

if __name__ == '__main__':
    App().run()
