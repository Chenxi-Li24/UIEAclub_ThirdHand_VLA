"""RGB-only Meituan inference. Models are injected from the existing owner."""
from pathlib import Path
import json
import math
import time
import cv2
import numpy as np

CONFIG = Path(__file__).resolve().parents[6] / "configs/meituan/vision.json"
COLORS = {"red": (255, 60, 60), "yellow": (255, 220, 0),
          "blue": (0, 150, 255), "green": (70, 230, 70), "unknown": (160, 160, 160)}

def load_defaults():
    return json.loads(CONFIG.read_text(encoding="utf-8"))

def parameters(value):
    if not isinstance(value, dict) or set(value) - {"prompt", "boxThreshold", "textThreshold"}:
        raise ValueError("invalid battery parameters")
    defaults = load_defaults()
    result = {key: value.get(key, defaults[key]) for key in ("prompt", "boxThreshold", "textThreshold")}
    if not isinstance(result["prompt"], str) or not 1 <= len(result["prompt"].strip()) <= 512:
        raise ValueError("prompt must contain 1..512 characters")
    result["prompt"] = result["prompt"].strip()
    for key in ("boxThreshold", "textThreshold"):
        v = result[key]
        if type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1:
            raise ValueError(key + " must be finite and within (0,1]")
    return result

def classify_color(rgb, mask, config):
    mask = np.asarray(mask, dtype=bool)
    if mask.shape != rgb.shape[:2]:
        raise ValueError("mask shape does not match RGB frame")
    eroded = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8),
                       iterations=config["erosionPixels"]).astype(bool)
    if int(eroded.sum()) < config["minMaskPixels"]:
        return {"color": "unknown", "colorScore": 0., "coloredFraction": 0.}
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    valid = eroded & (s >= 60) & (v >= 40)
    regions = {
        "red": (h < 10) | (h >= 170), "yellow": (h >= 15) & (h <= 38),
        "green": (h >= 39) & (h <= 90), "blue": (h >= 91) & (h <= 135),
    }
    counts = sorted(((int((valid & region).sum()), color) for color, region in regions.items()), reverse=True)
    colored = int(valid.sum())
    total = int(eroded.sum())
    score = counts[0][0] / max(1, colored)
    margin = (counts[0][0] - counts[1][0]) / max(1, colored)
    color = counts[0][1] if colored / total >= config["minColoredFraction"] and margin >= config["minColorMargin"] else "unknown"
    return {"color": color, "colorScore": score, "coloredFraction": colored / total}

def detect_masks(models, rgb, params):
    # Never create a backend or load weights here; never touch the bottle video session.
    from PIL import Image
    image = Image.fromarray(rgb, mode="RGB")
    inputs = models.dino_processor(images=image, text=[params["prompt"]], return_tensors="pt").to(models.device)
    with models.torch.inference_mode(), models.torch.autocast(device_type="cuda", dtype=models.torch.float16):
        output = models.dino_model(**inputs)
    result = models.dino_processor.post_process_grounded_object_detection(
        output, inputs.input_ids, threshold=params["boxThreshold"],
        text_threshold=params["textThreshold"], target_sizes=[image.size[::-1]])[0]
    rows = []
    height, width = rgb.shape[:2]
    for box, score in zip(result["boxes"], result["scores"]):
        box = [float(v) for v in box.tolist()]
        if not all(math.isfinite(v) for v in box):
            continue
        box = [max(0., min(width, box[0])), max(0., min(height, box[1])),
               max(0., min(width, box[2])), max(0., min(height, box[3]))]
        if box[2] > box[0] and box[3] > box[1]:
            rows.append({"box": box, "score": float(score.item())})
    if not rows:
        return []
    session = models.sam_processor.init_video_session(
        inference_device=models.device, inference_state_device="cpu",
        processing_device=models.device, video_storage_device="cpu",
        max_vision_features_cache_size=1, dtype=models.torch.bfloat16)
    try:
        sam_input = models.sam_processor(images=image, device=models.device, return_tensors="pt")
        size = tuple(int(v) for v in sam_input.original_sizes[0])
        for index, row in enumerate(rows):
            models.sam_processor.add_inputs_to_inference_session(
                inference_session=session, frame_idx=0, obj_ids=index,
                input_boxes=[[row["box"]]], original_size=size)
        session.obj_with_new_inputs = list(range(len(rows)))
        with models.torch.inference_mode(), models.torch.autocast(device_type="cuda", dtype=models.torch.float16):
            output = models.sam_model(inference_session=session, frame=sam_input.pixel_values[0])
        masks = models.sam_processor.post_process_masks(
            [output.pred_masks], original_sizes=sam_input.original_sizes)[0]
        for row, mask in zip(rows, masks):
            row["mask"] = np.asarray(mask.squeeze().detach().cpu().numpy(), dtype=bool)
        return [row for row in rows if "mask" in row]
    finally:
        reset = getattr(session, "reset_inference_session", None)
        if callable(reset):
            reset()

def recognize(models, rgb, frame_id, params):
    started = time.perf_counter()
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("RGB must be uint8 HxWx3")
    params = parameters(params)
    config = load_defaults()
    detections = []
    annotated = rgb.copy()
    for row in detect_masks(models, rgb, params):
        mask = np.asarray(row["mask"], dtype=bool)
        if mask.shape != rgb.shape[:2]:
            raise ValueError("mask shape does not match RGB frame")
        if int(mask.sum()) < config["minMaskPixels"]:
            continue
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        color = classify_color(rgb, mask, config)
        item = {"id": len(detections) + 1, "box": row["box"], "score": row["score"],
                "contour": contour.reshape(-1, 2).tolist(), **color}
        detections.append(item)
        paint = COLORS[color["color"]]
        cv2.drawContours(annotated, contours, -1, paint, 2)
        x1, y1, x2, y2 = [int(v) for v in row["box"]]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), paint, 2)
        cv2.putText(annotated, "#" + str(item["id"]) + " " + color["color"],
                    (x1, max(15, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, .6, paint, 2)
    ok, jpeg = cv2.imencode(".jpg", cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("battery JPEG encoding failed")
    return {"frameId": int(frame_id), "width": rgb.shape[1], "height": rgb.shape[0],
            "detections": detections, "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
            "parameters": params, "jpeg": jpeg.tobytes()}


class BatteryMailbox:
    """One latest request, processed by the existing serial inference loop."""
    def __init__(self, emit, *, infer=recognize):
        import threading
        self.emit = emit
        self.infer = infer
        self._lock = threading.Lock()
        self._pending = None
        self._generation = 0
        self._session = None

    def submit(self, session_id, request_id, params):
        for value in (session_id, request_id):
            if not isinstance(value, str) or not 1 <= len(value) <= 128:
                raise ValueError("invalid battery request/session id")
        params = parameters(params)
        with self._lock:
            if self._session != session_id:
                self._generation += 1
            self._session = session_id
            # ponytail: latest-slot mailbox; add a bounded queue only for offline batch jobs.
            self._pending = (session_id, request_id, params, self._generation)

    def cancel(self, session_id):
        with self._lock:
            if self._session == session_id:
                self._generation += 1
                self._session = None
                self._pending = None

    def process(self, frame, models):
        import base64
        import traceback
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is None:
            return
        session, request, params, generation = pending
        common = {"sessionId": session, "requestId": request, "frameId": int(frame.sequence),
                  "parameters": params, "timestamp": int(time.time() * 1000)}
        try:
            result = self.infer(models, frame.rgb, frame.sequence, params)
            jpeg = result.pop("jpeg")
            event = {**common, **result, "type": "meituan_result",
                     "jpegBase64": base64.b64encode(jpeg).decode("ascii")}
            log = {**common, "type": "meituan_log", "level": "info",
                   "elapsedMs": result.get("elapsedMs"), "detections": len(result["detections"])}
        except Exception as error:
            detail = {"message": str(error), "stack": traceback.format_exc()}
            try:
                detail["cuda"] = {
                    "allocatedBytes": models.torch.cuda.memory_allocated(models.device),
                    "reservedBytes": models.torch.cuda.memory_reserved(models.device)}
            except Exception:
                pass
            event = {**common, "type": "meituan_error", "error": detail}
            log = {**event, "type": "meituan_log", "level": "error"}
        self.emit(log)
        with self._lock:
            active = self._generation == generation and self._session == session
        if active:
            self.emit(event)
