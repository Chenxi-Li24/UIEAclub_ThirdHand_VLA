#!/usr/bin/env python3
"""Native Ubuntu window for the read-only person-follow overlay."""
import argparse
import base64
import json
import time
import urllib.request
from io import BytesIO
from PIL import Image, ImageTk
import tkinter as tk

class Window:
    def __init__(self, args):
        self.args = args
        self.seen_runtime = False
        self.offline_since = None
        self.root = tk.Tk()
        self.root.title("ThirdHand Person Follow - SAME SOURCE / READ ONLY")
        self.root.configure(bg="#090d12")
        frame = tk.Frame(self.root, width=640, height=480, bg="#090d12")
        frame.pack()
        frame.pack_propagate(False)
        self.label = tk.Label(frame, bg="#090d12")
        self.label.pack(expand=True)
        self.status = tk.Label(self.root, text="starting", fg="#9ff", bg="#090d12",
                               font=("monospace", 11), wraplength=620, height=4)
        self.status.pack(fill="x")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(30, self.tick)

    def observation(self):
        try:
            with urllib.request.urlopen(self.args.observation, timeout=.3) as response:
                return json.load(response)
        except Exception as exc:
            return {"state": {"status": "offline", "reason": str(exc)}}

    def tick(self):
        packet = self.observation()
        state = packet.get("state", {})
        jpeg = packet.get("jpeg_base64")
        if state.get("status") == "offline":
            if self.offline_since is None:
                self.offline_since = time.monotonic()
            if self.seen_runtime and time.monotonic() - self.offline_since >= 2:
                self.close()
                return
        else:
            self.seen_runtime = True
            self.offline_since = None
        if jpeg:
            image = Image.open(BytesIO(base64.b64decode(jpeg)))
            image.thumbnail((640, 480))
            photo = ImageTk.PhotoImage(image)
            self.label.configure(image=photo)
            self.label.image = photo
        elif state.get("status") == "offline":
            self.label.configure(image="")
            self.label.image = None
        control = state.get("control", {})
        mode = state.get("mode", "-") if state.get("motion_enabled") else "DRY RUN"
        self.status.configure(text=(
            f"{mode} | {state.get('status')} | frame={state.get('frame_id')} | "
            f"used={state.get('used_by_last_command')}\n"
            f"{control.get('request_id', '-')} | {state.get('reason', '-')}"
        ))
        self.root.after(200, self.tick)

    def close(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--observation", default="http://127.0.0.1:31024/api/frame")
    Window(parser.parse_args()).run()


if __name__ == "__main__":
    main()
