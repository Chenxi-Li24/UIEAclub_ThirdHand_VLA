#!/usr/bin/env python3
"""Native Ubuntu window for the read-only person-follow overlay."""
import argparse,json,sys,time,urllib.request
from pathlib import Path
import cv2
from PIL import Image,ImageTk
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from dummy.vision_service_tracker import MjpegReader
from dummy.person_follow.visualization import render_overlay

class Window:
 def __init__(self,args):
  self.args=args; self.reader=MjpegReader(args.stream); self.reader.start(); self.root=tk.Tk(); self.root.title("ThirdHand Person Follow — READ ONLY"); self.root.configure(bg="#090d12"); self.label=tk.Label(self.root,bg="#090d12"); self.label.pack(); self.status=tk.Label(self.root,text="starting",fg="#9ff",bg="#090d12",font=("monospace",11)); self.status.pack(fill="x"); self.root.protocol("WM_DELETE_WINDOW",self.close); self.root.after(30,self.tick)
 def observation(self):
  try: return json.load(urllib.request.urlopen(self.args.observation,timeout=.25))
  except Exception as e: return {"identity_state":"LOST","robot":{"reason_code":f"OBSERVATION_UNAVAILABLE:{e}"}}
 def tick(self):
  frame,error=self.reader.latest(); state=self.observation()
  if frame is not None:
   out=render_overlay(frame,state); rgb=cv2.cvtColor(out,cv2.COLOR_BGR2RGB); image=ImageTk.PhotoImage(Image.fromarray(rgb)); self.label.configure(image=image); self.label.image=image
  self.status.configure(text=f"READ ONLY | vision 3100 | {state.get('identity_state',state.get('status','searching'))} | {error or 'stream ok'}")
  self.root.after(40,self.tick)
 def close(self): self.reader.close(); self.root.destroy()
 def run(self): self.root.mainloop()
def main():
 p=argparse.ArgumentParser(); p.add_argument("--stream",default="http://127.0.0.1:3100/camera/xvisio/vision"); p.add_argument("--observation",default="http://127.0.0.1:3100/api/vision/person-follow/observation"); a=p.parse_args(); Window(a).run()
if __name__=="__main__": main()
