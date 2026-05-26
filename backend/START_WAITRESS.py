#!/usr/bin/env python
"""
Start FairTax backend with Waitress WSGI server
Production-ready server that works on Windows
"""

from waitress import serve
from app import app
import os

if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5000))
    workers = int(os.getenv('WORKERS', 4))

    print(f"""
    ========================================================
    FairTax Backend - Waitress WSGI Server
    ========================================================

    Starting Waitress server...
    [OK] Host: {host}
    [OK] Port: {port}
    [OK] Threads: {workers}

    Navigate to http://localhost:{port}
    Press CTRL+C to stop
    """)

    serve(
        app,
        host=host,
        port=port,
        threads=workers,
        _quiet=False
    )
