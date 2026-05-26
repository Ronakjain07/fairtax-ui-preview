import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import logging
logging.basicConfig(level=logging.DEBUG)

from app import app

@app.before_request
def log_req():
    print(f"[REQUEST] {request.method} {request.path}", flush=True)

# Start Flask with logging enabled
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
