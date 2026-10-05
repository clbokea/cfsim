"""Browser view and room editor: a small web server inside the simulator.

    python -m cfsim --viewer browser my_script.py    3D view in the browser
    python -m cfsim --editor                         make a world from a floor plan

The server only listens on 127.0.0.1 and uses nothing but the standard
library. The pages are in cfsim/web/ (three.js is bundled in web/vendor/).

The engine calls WebView.send() with the same messages it writes to the
window viewer (world / state / msg / end, see engine.py). Every open page
gets them as Server-Sent Events from /events. A page that connects later
first gets the world, the latest state with the trails, and the last
messages, so it can draw the current picture straight away.
"""
import base64
import http.server
import json
import os
import queue
import re
import threading
import time
import urllib.parse
import uuid
import webbrowser

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
DEFAULT_PORT = 8765
TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
         '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg',
         '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml', '.md': 'text/plain; charset=utf-8',
         '': 'text/plain; charset=utf-8'}
IMAGE_TYPES = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'}


class WebView:
    """The web server. One per process; start it with start()."""

    def __init__(self, port=DEFAULT_PORT, save_dir=None):
        self.port = port
        self.save_dir = save_dir or os.getcwd()
        self.session = uuid.uuid4().hex[:8]       # pages reset when this changes
        self.world = None                         # the 'world' message
        self.world_image = None                   # path of the floor plan image
        self.state = None                         # the latest 'state' message
        self.trails = {}
        self.msgs = []
        self.ended = False
        self._clients = []
        self._lock = threading.Lock()
        self._httpd = None
        self.url = None

    # ------------------------------------------------------------ server
    def start(self):
        handler = _make_handler(self)
        for port in range(self.port, self.port + 20):
            try:
                self._httpd = _Server(('127.0.0.1', port), handler)
                break
            except OSError:                       # port in use: try the next one
                continue
        else:
            raise OSError(f'no free port between {self.port} and {self.port + 19}')
        self.port = self._httpd.server_address[1]
        self.url = f'http://127.0.0.1:{self.port}/'
        threading.Thread(target=self._httpd.serve_forever, name='cfsim-web',
                         daemon=True).start()
        return self

    def open_page(self, path='', wait=1.5):
        """Open the page in the browser - unless a page that is still open from
        an earlier run reconnects within `wait` seconds (no new tab every run)."""
        def run():
            end = time.monotonic() + wait
            while time.monotonic() < end:
                if self.client_count():
                    return
                time.sleep(0.1)
            try:
                webbrowser.open(self.url + path)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def client_count(self):
        with self._lock:
            return len(self._clients)

    def wait_for_client(self, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end and not self.client_count():
            time.sleep(0.1)
        return self.client_count() > 0

    # ----------------------------------------------------------- messages
    def send(self, obj):
        kind = obj.get('type')
        with self._lock:
            if kind == 'world':
                world = dict(obj['world'])
                self.world_image = world.pop('image_path', None)
                world['image'] = bool(self.world_image)
                obj = {'type': 'world', 'world': world, 'session': self.session}
                self.world = obj
            elif kind == 'state':
                if 'trails' in obj:
                    self.trails = obj['trails']
                self.state = obj
            elif kind == 'msg':
                self.msgs = (self.msgs + [obj['text']])[-3:]
            elif kind == 'end':
                self.ended = True
            data = json.dumps(obj)
            for q in self._clients:
                try:
                    q.put_nowait(data)
                except queue.Full:                # a slow page skips some pictures
                    pass

    def _hello(self):
        """What a newly connected page needs to draw the current picture."""
        with self._lock:
            out = []
            if self.world:
                out.append(self.world)
            if self.state:
                out.append(dict(self.state, trails=self.trails))
            out += [{'type': 'msg', 'text': t} for t in self.msgs]
            if self.ended:
                out.append({'type': 'end'})
            return [json.dumps(o) for o in out]

    def _add_client(self):
        q = queue.Queue(maxsize=200)
        with self._lock:
            self._clients.append(q)
        return q

    def _remove_client(self, q):
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    # ------------------------------------------------------------- editor
    def save_world(self, req):
        """Save a world made in the editor (and its floor plan) in save_dir."""
        name = str(req.get('name', '')).strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', name):
            return 400, {'error': 'Use only letters, digits, - and _ in the name.'}
        txt = os.path.join(self.save_dir, name + '.txt')
        files = [txt]
        img_ext = str(req.get('image_ext', '')).lower()
        if req.get('image_b64'):
            if img_ext not in IMAGE_TYPES:
                return 400, {'error': 'The floor plan must be PNG or JPEG.'}
            files.append(os.path.join(self.save_dir, f'{name}.{img_ext}'))
        existing = [f for f in files if os.path.exists(f)]
        if existing and not req.get('overwrite'):
            return 409, {'error': 'exists', 'files': [os.path.basename(f) for f in existing]}
        with open(txt, 'w', encoding='utf-8', newline='\n') as f:
            f.write(str(req.get('text', '')))
        if len(files) > 1:
            with open(files[1], 'wb') as f:
                f.write(base64.b64decode(req['image_b64']))
        return 200, {'files': [os.path.basename(f) for f in files],
                     'folder': self.save_dir}


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # Reuse the port right after the previous run (its old connections linger
    # in TIME_WAIT). Not on Windows: there SO_REUSEADDR would let two running
    # servers share a port, and a second cfsim run must get its own port.
    allow_reuse_address = os.name != 'nt'


def _make_handler(view):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):            # keep the terminal quiet
            pass

        # ------------------------------------------------------- helpers
        def _send(self, code, body, ctype='text/plain; charset=utf-8'):
            if isinstance(body, str):
                body = body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj), 'application/json')

        def _file(self, path):
            if not os.path.isfile(path):
                return self._send(404, 'not found')
            ext = os.path.splitext(path)[1].lower()
            with open(path, 'rb') as f:
                self._send(200, f.read(), TYPES.get(ext, 'application/octet-stream'))

        # -------------------------------------------------------- routes
        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path in ('/', '/index.html'):
                return self._file(os.path.join(STATIC_DIR, 'viewer.html'))
            if path in ('/editor', '/editor.html'):
                return self._file(os.path.join(STATIC_DIR, 'editor.html'))
            if path == '/events':
                return self._events()
            if path == '/world-image':
                return self._file(view.world_image) if view.world_image \
                    else self._send(404, 'no floor plan')
            if path.startswith('/static/'):
                rel = os.path.normpath(path[len('/static/'):]).lstrip(os.sep)
                full = os.path.join(STATIC_DIR, rel)
                if rel.startswith('..') or not full.startswith(STATIC_DIR):
                    return self._send(403, 'forbidden')
                return self._file(full)
            return self._send(404, 'not found')

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path != '/api/save-world':
                return self._send(404, 'not found')
            try:
                n = int(self.headers.get('Content-Length', 0))
                req = json.loads(self.rfile.read(n))
                code, out = view.save_world(req)
            except Exception as e:
                code, out = 500, {'error': f'{type(e).__name__}: {e}'}
            self._json(code, out)

        def _events(self):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            q = view._add_client()
            try:
                # reconnect quickly, so a page left open picks up the next run
                self.wfile.write(b'retry: 1000\n\n')
                for data in view._hello():
                    self.wfile.write(f'data: {data}\n\n'.encode('utf-8'))
                self.wfile.flush()
                while True:
                    try:
                        data = q.get(timeout=10)
                        self.wfile.write(f'data: {data}\n\n'.encode('utf-8'))
                    except queue.Empty:
                        self.wfile.write(b': ping\n\n')      # keep the connection alive
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                view._remove_client(q)
                self.close_connection = True

    return Handler


def run_editor(port=DEFAULT_PORT, open_browser=True):
    """python -m cfsim --editor: serve the room editor until Ctrl+C."""
    view = WebView(port).start()
    print(f'[cfsim] Room editor: {view.url}editor', flush=True)
    print(f'[cfsim] Worlds are saved in {view.save_dir}', flush=True)
    print('[cfsim] Press Ctrl+C to stop.', flush=True)
    if open_browser:
        webbrowser.open(view.url + 'editor')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
