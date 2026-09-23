#!/usr/bin/env python3
"""Launch the offline GTK viewer or CPU snapshot command."""
from panorama_viewer.cli import ViewerCommand

if __name__ == '__main__':
    raise SystemExit(ViewerCommand.run())
