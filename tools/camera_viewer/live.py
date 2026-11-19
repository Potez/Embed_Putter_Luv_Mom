# Live OV7670 viewer with detection boxes: http://localhost:8765
# - frames + on-board PersonDetector verdict come from the ESP32 over USB
# - YOLOv8n on this laptop draws a box around every person
import os, termios, time, fcntl, struct, threading, json
import numpy as np, cv2
from ultralytics import YOLO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = os.environ.get('OV7670_PORT', '/dev/cu.usbserial-0001')   # Windows/Linux: set OV7670_PORT
L, WD, SCALE = 319, 159, 4
model = YOLO(os.path.join(os.path.dirname(__file__), 'yolov8n.pt') if os.path.exists(os.path.join(os.path.dirname(__file__), 'yolov8n.pt')) else 'yolov8n.pt')
state = {'jpg': b'', 'n': 0, 'fps': 0.0, 'board': None, 'yolo': []}

def open_port():
    fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd); a[0]=0; a[1]=0; a[2]=termios.CS8|termios.CREAD|termios.CLOCAL; a[3]=0; a[4]=a[5]=termios.B230400
    termios.tcsetattr(fd, termios.TCSANOW, a); fcntl.ioctl(fd, 0x80045402, struct.pack('L', 921600))
    return fd

def grab(fd):
    try:
        while os.read(fd, 65536): pass
    except BlockingIOError: pass
    os.write(fd, b's'); buf = b''; t = time.time() + 2
    while time.time() < t:
        try: buf += os.read(fd, 65536)
        except BlockingIOError: time.sleep(0.003)
        i = buf.find(b'FRAME ')
        if i < 0: continue
        he = buf.find(b'\n', i)
        if he < 0: continue
        try: n = int(buf[i+6:he].split()[0])
        except (ValueError, IndexError): return None, None
        end = he + 1 + n
        if len(buf) < end: continue
        ds = buf.find(b'\nDET ', end - 1)            # status line right after the image only
        de = buf.find(b'\n', ds + 5) if ds >= 0 else -1
        if de < 0: continue
        try:
            d = buf[ds+5:de].split()
            board = {'person': float(d[0]), 'none': float(d[1]), 'is': d[2] == b'1', 'ms': int(d[3]), 'count': int(d[4])}
        except (ValueError, IndexError):
            board = None                                # garbled status: keep the frame anyway
        return buf[he+1:end], board
    return None, None

def decode(raw):
    a = np.frombuffer(raw, np.uint8)
    def rows(K):
        H = (len(a) - K) // L
        return a[K:K+H*L].reshape(H, L)[:, :2*WD]
    def score(K):
        r = rows(K)[3::10].astype(np.int32)
        g = (((r[:, 0::2] << 8) | r[:, 1::2]) >> 5) & 63
        return np.abs(np.diff(g[:, ::2], axis=1)).sum()
    K = min(range(L), key=score)
    r = rows(K).astype(np.uint16)
    p = (r[:, 0::2] << 8) | r[:, 1::2]
    rgb = np.stack([((p >> 11) & 31) * 255 // 31, ((p >> 5) & 63) * 255 // 63, (p & 31) * 255 // 31], -1).astype(np.uint8)
    return np.ascontiguousarray(np.rot90(rgb, 1))   # camera is mounted sideways -> upright

def loop():
    fd = open_port(); last = time.time()
    while True:
      try:
        raw, board = grab(fd)
        if raw is None or len(raw) < L * 60: continue
        rgb = decode(raw)
        big = cv2.resize(rgb, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_NEAREST)
        bgr = cv2.cvtColor(big, cv2.COLOR_RGB2BGR)
        res = model.predict(bgr, imgsz=320, classes=[0], conf=0.35, verbose=False)[0]
        boxes = []
        for b in res.boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0].tolist()); c = float(b.conf[0])
            boxes.append(c)
            cv2.rectangle(bgr, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(bgr, f'person {c:.2f}', (x1 + 3, max(y1 - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        ok, jpg = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        now = time.time()
        state.update(jpg=jpg.tobytes(), n=state['n'] + 1, board=board or state['board'], yolo=boxes,
                     fps=0.7 * state['fps'] + 0.3 / max(now - last, 1e-3)); last = now
      except Exception as e:                            # never let the capture thread die
        print('capture error:', repr(e), flush=True); time.sleep(0.2)

PAGE = b'''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>OV7670 Live</title>
<style>body{margin:0;background:#111;color:#ddd;font:14px system-ui;display:flex;flex-direction:column;align-items:center;gap:10px;padding:16px}
img{height:min(72vh,640px);max-width:100%;border-radius:8px;background:#000}
.row{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}.card{background:#1d1d1d;border-radius:8px;padding:8px 14px;min-width:220px}
.big{font-size:20px;font-weight:600}.yes{color:#4ade80}.no{color:#9ca3af}.muted{color:#888;font-size:12px}</style>
<h3 style=margin:0>OV7670 live + detection</h3><img id=v>
<div class=row><div class=card><div class=muted>ESP32 on-board (TFLite person model)</div><div id=b class=big>-</div><div id=bs class=muted></div></div>
<div class=card><div class=muted>Laptop YOLOv8n (boxes)</div><div id=y class=big>-</div><div id=st class=muted></div></div></div>
<script>const $=id=>document.getElementById(id);
async function tick(){try{const r=await fetch('/frame.jpg?'+Date.now());if(r.ok){const u=URL.createObjectURL(await r.blob());const o=$('v').src;$('v').src=u;if(o.startsWith('blob:'))URL.revokeObjectURL(o);
const s=await(await fetch('/stat')).json();const b=s.board;
if(b){$('b').textContent=b.is?'PERSON':'nobody';$('b').className='big '+(b.is?'yes':'no');$('bs').textContent='person '+b.person.toFixed(2)+' \\u00b7 '+b.ms+' ms/check \\u00b7 check #'+b.count;}
$('y').textContent=s.yolo.length?s.yolo.length+' person'+(s.yolo.length>1?'s':''):'nobody';$('y').className='big '+(s.yolo.length?'yes':'no');
$('st').textContent='frame #'+s.n+' \\u00b7 ~'+s.fps.toFixed(1)+' fps';}}catch(e){$('st').textContent='waiting...'}setTimeout(tick,120)}tick();</script>'''

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith('/frame.jpg'):
            if not state['jpg']: self.send_response(503); self.end_headers(); return
            body, ct = state['jpg'], 'image/jpeg'
        elif self.path.startswith('/stat'):
            body, ct = json.dumps({k: state[k] for k in ('n', 'fps', 'board', 'yolo')}).encode(), 'application/json'
        else: body, ct = PAGE, 'text/html; charset=utf-8'
        self.send_response(200); self.send_header('Content-Type', ct); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(body)

threading.Thread(target=loop, daemon=True).start()
print('live on http://localhost:8765', flush=True)
ThreadingHTTPServer(('127.0.0.1', 8765), H).serve_forever()
