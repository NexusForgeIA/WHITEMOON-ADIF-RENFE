import base64, json, os, sys, threading, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402


def start():
    server.APP = server.App()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def get(port, path, pw=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if pw is not None:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"u:{pw}".encode()).decode())
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code


def test_password_gate_protects_dashboard_and_api_but_not_health():
    os.environ["RG_VIEW_PASSWORD"] = "secreto-de-prueba"
    srv = start()
    try:
        p = srv.server_address[1]
        assert get(p, "/") == 401 and get(p, "/api/snapshot") == 401 and get(p, "/api/systems") == 401
        assert get(p, "/api/snapshot", "mala") == 401
        assert get(p, "/", "secreto-de-prueba") == 200 and get(p, "/api/snapshot", "secreto-de-prueba") == 200
        assert get(p, "/api/health") in (200, 503)   # monitorización sin contraseña
    finally:
        os.environ.pop("RG_VIEW_PASSWORD")
        srv.shutdown()


def test_without_password_everything_is_open_demo_mode():
    os.environ.pop("RG_VIEW_PASSWORD", None)
    srv = start()
    try:
        assert get(srv.server_address[1], "/") == 200
    finally:
        srv.shutdown()
