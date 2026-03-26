"""Health Check Server — GET /health on port 8080"""

import threading, logging, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
LISBON_TZ = pytz.timezone("Europe/Lisbon")
_start_time = datetime.now(LISBON_TZ)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            now = datetime.now(LISBON_TZ)
            body = json.dumps({
                "status": "ok",
                "timestamp": now.isoformat(),
                "uptime": str(now - _start_time).split(".")[0],
                "bot": "Stock Signal Bot MTF V3"
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def start_health_server(port: int = 8080):
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info(f"Health server on :{port}/health")
    return server
