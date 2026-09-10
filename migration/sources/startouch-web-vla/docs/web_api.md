# Web API Reference
Base URL: http://<host>:8000

## REST

### Robot
GET /api/robot/status -> {"connected":true,"joints":[...],"pose":[...],"state":"idle"}
POST /api/robot/jog?dx=&dy=&dz= -> jog end-effector
POST /api/robot/home -> move to home
POST /api/robot/estop -> emergency stop

### Camera
GET /api/camera/stream -> MJPEG video
GET /api/camera/snapshot -> single JPEG frame

### Task
GET /api/task/list -> {"tasks":["pick_place","ar_tag_sort"]}
POST /api/task/start?task_name=pick_place
POST /api/task/stop
POST /api/task/pause
POST /api/task/resume
GET /api/task/status -> {"task":"pick_place","state":"running","elapsed":12.5}

## WebSocket ws://<host>:8000/ws

robot_state: {"type":"robot_state","connected":true,"joints":[...],"pose":[...]}
camera_frame: {"type":"camera_frame","image":"<base64>","detections":[...],"fps":15}
task_event: {"type":"task_event","task":"pick_place","state":"APPROACH","elapsed":3.2}
log: {"type":"log","level":"info","timestamp":"...","message":"..."}
