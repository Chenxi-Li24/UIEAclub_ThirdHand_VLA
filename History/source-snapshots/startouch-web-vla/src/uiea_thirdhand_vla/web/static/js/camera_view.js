// camera_view.js — Camera feed with detection overlay
const cameraFeed = document.getElementById('camera-feed');
const detectionOverlay = document.getElementById('detection-overlay');
const overlayCtx = detectionOverlay.getContext('2d');

function updateCameraFrame(data) {
    if (data.image) {
        cameraFeed.src = data:image/jpeg;base64,;
    }
    if (data.detections && overlayCtx) {
        drawDetections(data.detections);
    }
    document.getElementById('fps-counter').textContent = FPS: ;
}

function drawDetections(detections) {
    const w = detectionOverlay.width;
    const h = detectionOverlay.height;
    overlayCtx.clearRect(0, 0, w, h);
    overlayCtx.strokeStyle = '#3fb950';
    overlayCtx.lineWidth = 2;
    overlayCtx.font = '14px sans-serif';
    overlayCtx.fillStyle = '#3fb950';
    detections.forEach((d) => {
        // Draw detection box and label
        // TODO: implement
    });
}
