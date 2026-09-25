#!/usr/bin/env python3
"""Check configured SOCKS proxies, including commented-out endpoints."""
from panorama_archive.proxy_check import ProxyCheckCommand

if __name__ == '__main__':
    raise SystemExit(ProxyCheckCommand.run())
