#!/usr/bin/env python3

"""
Script monitors for new panorams in panorama_log and initiates a download
for new ones
"""

import os
import sys
import time
import psycopg
import subprocess

from psycopg.rows import dict_row

DB_CONFIG = {
    "dbname": "panoramas",
    "user": "allarchive",
    "password": "allarchive",
    "host": "localhost",
    "port": 5432
}

class App():

    def download(self, panorama_id: str, provider: str):
        command = ['./get.sh', panorama_id]

        if provider == 'google':
            os.system(f'./pano-google.py {panorama_id} 5')
            os.system(f"./merge.py {panorama_id} 5")
        elif provider == 'yandex':
            os.system(f'./pano.py {panorama_id} 0')
            os.system(f"./merge.py {panorama_id} 0")
        else:
            print(f"Unknown provider {provider}")
            return

    def monitor(self):
        query = "select distinct external_id, provider " \
                "  from aa.panorama_log "

        with psycopg.connect(**DB_CONFIG) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query)
                for row in cursor.fetchall():
                    if not os.path.exists(f"./panos/{row['external_id']}.jpg"):
                        print(f"Starting to download {row['external_id']}")
                        self.download(row['external_id'], row['provider'])
                        break

    def run(self):
        while True:
            self.monitor()
            print("Sleeping for 10 s")
            time.sleep(10)

if __name__ == '__main__':
    sys.exit(App().run())
