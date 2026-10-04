#!/usr/bin/env python3
"""Read-only browser dashboard for the production person-follow pipeline."""
import argparse,json,sys,threading,time,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from dummy.vision_service_tracker import MjpegReader
from dummy.person_follow.visualization import render_overlay,dashboard_snapshot
class Shared:
 def __init__(self): self.jpeg=None; self.state={}; self.lock=threading.Lock(); self.stop=False
def loop(s,stream,api):
 r=MjpegReader(stream); r.start()
 while not s.stop:
  frame,_=r.latest()
  try: state=json.load(urllib.request.urlopen(api,timeout=.5))
  except Exception as e: state={"identity_state":"LOST","gateway":{"reason_code":f"OBSERVATION_UNAVAILABLE:{e}"}}
  if frame is not None:
   ok,j=cv2.imencode(".jpg",render_overlay(frame,state),[cv2.IMWRITE_JPEG_QUALITY,85])
   if ok:
    with s.lock: s.jpeg=j.tobytes(); s.state=dashboard_snapshot(state)
  time.sleep(.04)
 r.close()
def handler(s):
 class H(BaseHTTPRequestHandler):
  def log_message(self,*a): pass
  def do_GET(self):
   if self.path=="/api/status":
    with s.lock: body=json.dumps(s.state).encode()
    self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(body); return
   if self.path in ("/","/index.html"):
    body=b'<!doctype html><meta charset=utf-8><title>ThirdHand Person Follow</title><style>body{background:#090d12;color:#d9f7ff;font:15px monospace}img{max-width:100%;border:1px solid #25d9ff}pre{white-space:pre-wrap}</style><h2>Person Follow Read-only Debug Dashboard</h2><img src=/stream.mjpg><pre id=s></pre><script>setInterval(()=>fetch("/api/status").then(r=>r.json()).then(x=>s.textContent=JSON.stringify(x,null,2)),250)</script>'
    self.send_response(200); self.end_headers(); self.wfile.write(body); return
   if self.path!="/stream.mjpg": self.send_error(404); return
   self.send_response(200); self.send_header("Content-Type","multipart/x-mixed-replace; boundary=frame"); self.end_headers()
   while not s.stop:
    with s.lock: j=s.jpeg
    if j:
     try: self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "+str(len(j)).encode()+b"\r\n\r\n"+j+b"\r\n")
     except OSError: break
    time.sleep(.05)
 return H
def main():
 p=argparse.ArgumentParser(); p.add_argument("--host",default="127.0.0.1"); p.add_argument("--port",type=int,default=31024); p.add_argument("--stream",default="http://127.0.0.1:3100/camera/xvisio/vision"); p.add_argument("--observation",default="http://127.0.0.1:3100/api/vision/person-follow/observation"); a=p.parse_args(); s=Shared(); threading.Thread(target=loop,args=(s,a.stream,a.observation),daemon=True).start(); print(f"visualization http://{a.host}:{a.port}",flush=True); ThreadingHTTPServer((a.host,a.port),handler(s)).serve_forever()
if __name__=="__main__": main()
