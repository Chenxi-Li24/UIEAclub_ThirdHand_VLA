#!/usr/bin/env python3
"""Native Ubuntu desktop window for the existing ThirdHand Vision Service stream."""

import argparse
import os
import threading
import time
import tkinter as tk
import urllib.request
from io import BytesIO

from PIL import Image, ImageTk


class StreamReader:
    def __init__(self, url):
        self.url = url
        self.lock = threading.Lock()
        self.image = None
        self.status = "starting"
        self.stop = False

    def start(self):
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self):
        while not self.stop:
            try:
                with urllib.request.urlopen(self.url, timeout=5) as response:
                    buf = b""
                    while not self.stop:
                        chunk = response.read(8192)
                        if not chunk:
                            raise EOFError("stream ended")
                        buf += chunk
                        start = buf.find(b"\xff\xd8")
                        end = buf.find(b"\xff\xd9", start + 2)
                        if start >= 0 and end >= 0:
                            jpg = buf[start:end + 2]
                            buf = buf[end + 2:]
                            img = Image.open(BytesIO(jpg)).convert("RGB")
                            with self.lock:
                                self.image = img
                                self.status = f"ok {img.width}x{img.height}"
            except Exception as exc:
                with self.lock:
                    self.status = f"stream error: {exc}"
                time.sleep(1)


class App:
    def __init__(self, root, reader):
        self.root = root
        self.reader = reader
        self.label = tk.Label(root, bg="black")
        self.label.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="starting")
        tk.Label(root, textvariable=self.status, anchor="w").pack(fill="x")
        self.photo = None
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    def tick(self):
        with self.reader.lock:
            img = self.reader.image.copy() if self.reader.image is not None else None
            status = self.reader.status
        self.status.set(status)
        if img is not None:
            img.thumbnail((1100, 800))
            self.photo = ImageTk.PhotoImage(img)
            self.label.configure(image=self.photo)
        self.root.after(33, self.tick)

    def close(self):
        self.reader.stop = True
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--display", default=os.environ.get("DISPLAY") or ":1")
    parser.add_argument("--url", default="http://127.0.0.1:3100/camera/xvisio/vision")
    args = parser.parse_args()
    os.environ.setdefault("DISPLAY", args.display)

    reader = StreamReader(args.url)
    reader.start()
    root = tk.Tk()
    root.title("ThirdHand Vision Stream")
    root.geometry("1100x850")
    App(root, reader)
    root.mainloop()


if __name__ == "__main__":
    main()
