#!/usr/bin/env python3
"""Operator calibration UI using existing service ports only. Never commands a robot."""
import collections
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cv2
import numpy as np
from handeye_core import flange_transform, validate_state, match_state, fit_camera, solve_handeye

SERIAL='250801DR48FP25002738'
VISION='http://127.0.0.1:3100'
ROBOT='ws://192.168.58.68:9983/ws'
LIVE=Path(os.environ.get('THIRDHAND_LIVE_ROOT',str(Path.home()/'ThirdHand'/'UIEAclub_ThirdHand_VLA'))).resolve()
BOARD={'squares_x':9,'squares_y':12,'square_length_m':.015,'marker_length_m':.01125,'dictionary':'DICT_5X5_100'}


class CalibrationSession:
    def __init__(self, root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.samples=[];self.last_frame=-1;self.overlay=None;self.result=None
        self.dictionary=cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
        self.board=cv2.aruco.CharucoBoard((9,12),.015,.01125,self.dictionary)
        self.detector=cv2.aruco.ArucoDetector(self.dictionary,cv2.aruco.DetectorParameters())
        manifest=self.root/'samples.json'
        if manifest.exists():
            samples=json.loads(manifest.read_text())
            if not isinstance(samples,list):raise ValueError('invalid_saved_session')
            for i,sample in enumerate(samples,1):
                with np.load(self.root/f'sample-{i:04d}.npz',allow_pickle=False) as bundle:
                    if json.loads(str(bundle['metadata_json']))!=sample:raise ValueError('saved_sample_manifest_mismatch')
            self.samples=samples
            self.last_frame=samples[-1]['frame']['frame_id'] if samples else -1
        candidates=sorted(self.root.glob('candidate-*.json'))
        if candidates:self.result=json.loads(candidates[-1].read_text())

    def capture(self,bundle,states,now_ns):
        metadata=bundle['metadata'];rgb=bundle['rgb']
        if (metadata.get('schema')!='thirdhand-raw-rgbd-frame-v1' or metadata.get('camera_serial')!=SERIAL
            or metadata.get('point_frame')!='xvisio_color' or metadata.get('length_unit')!='m'
            or rgb.dtype!=np.uint8 or rgb.shape!=(480,640,3)):
            raise ValueError('camera_identity_or_stream_shape_mismatch')
        frame=metadata.get('frame_id')
        if type(frame) is not int or frame<=self.last_frame:raise ValueError('duplicate_or_replayed_camera_frame')
        state=match_state(states,metadata.get('monotonic_ns'),now_ns)
        if not states or validate_state(states[-1],now_ns) is None:raise ValueError('robot_not_stationary_now')
        flange=flange_transform(state['flange_position_m'],state['flange_euler_rad'])
        for sample in self.samples:
            old=np.asarray(sample['T_base_flange'])
            angle=float(np.linalg.norm(cv2.Rodrigues(old[:3,:3].T@flange[:3,:3])[0]))
            if angle<.05 and np.linalg.norm(old[:3,3]-flange[:3,3])<.01:
                raise ValueError('pose_too_similar_move_to_a_new_safe_orientation')
        gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        corners,ids,_=self.detector.detectMarkers(gray)
        if ids is None or len(ids)<20 or len(set(map(int,ids.ravel())))!=len(ids):
            raise ValueError('need_20_unique_board_markers_visible')
        if not set(map(int,ids.ravel())).issubset(set(map(int,self.board.getIds().ravel()))):
            raise ValueError('unexpected_board_marker_ids')
        charuco,corner_ids,_,_=cv2.aruco.CharucoDetector(self.board).detectBoard(gray)
        count=0 if corner_ids is None else len(corner_ids)
        if count<30:raise ValueError('need_30_charuco_corners_visible')
        obj=self.board.getChessboardCorners()[corner_ids.ravel()].astype(float)
        extent=np.ptp(obj,axis=0)
        if extent[0]<.5*9*.015 or extent[1]<.5*12*.015:raise ValueError('board_coverage_too_small')
        sample={'frame':metadata,'robot_state':state,'T_base_flange':flange.tolist(),
                'sync_delta_ms':(state['producer_monotonic_ns']-metadata['monotonic_ns'])/1e6,
                'object_points':obj.tolist(),'image_points':charuco.reshape(-1,2).tolist(),
                'corner_ids':corner_ids.ravel().tolist(),'image_size':[640,480]}
        number=len(self.samples)+1
        with (self.root/f'sample-{number:04d}.npz').open('xb') as f:
            np.savez_compressed(f,rgb=rgb,metadata_json=json.dumps(sample,allow_nan=False))
        overlay=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
        cv2.aruco.drawDetectedMarkers(overlay,corners,ids)
        cv2.aruco.drawDetectedCornersCharuco(overlay,charuco,corner_ids)
        self.overlay=cv2.imencode('.jpg',overlay)[1].tobytes()
        self.samples.append(sample);self.last_frame=frame
        self._save('samples.json',self.samples,replace=True)
        return {'pairs':number,'corners':int(count),'markers':len(ids),'sync_delta_ms':sample['sync_delta_ms']}

    def _save(self,name,value,replace=False):
        target=self.root/name
        pending=self.root/(name+'.pending-'+secrets.token_hex(8)) if replace else target
        with pending.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)
        if replace:os.replace(pending,target)

    def compute(self):
        camera=fit_camera(self.samples,(640,480))
        pairs=[(s['T_base_flange'],b) for s,b in zip(self.samples,camera.pop('board_transforms'))]
        result=solve_handeye(pairs)
        manifest=self.freeze_manifest()
        result.update(schema='thirdhand-port-fed-handeye-candidate-v1',camera_serial=SERIAL,
                      extrinsic_semantics='T_flange_camera',robot_state_semantics='T_base_flange',
                      board=BOARD,camera_model=camera,robot_source=ROBOT,vision_source=VISION,
                      samples_manifest=manifest,
                      warnings=['candidate_only_not_grasp_approved','TCP_and_path_not_validated',
                                'fisheye_model_is_fitted_not_factory_SEUCM','operator_must_keep_board_fixed',
                                'RGB_ToF_hardware_synchronization_not_independently_validated'])
        self._save(f'candidate-{time.time_ns()}.json',result)
        self.result=result
        return result

    def freeze_manifest(self):
        artifacts=[]
        for i,_ in enumerate(self.samples,1):
            name=f'sample-{i:04d}.npz'
            artifacts.append({'filename':name,'sha256':hashlib.sha256((self.root/name).read_bytes()).hexdigest()})
        name=f'manifest-{time.time_ns()}.json'
        self._save(name,{'board':BOARD,'samples':self.samples,'artifacts':artifacts})
        return {'filename':name,'sha256':hashlib.sha256((self.root/name).read_bytes()).hexdigest()}


HTML='''<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><title>手眼标定 · 端口只读采样</title>
<style>body{margin:0;background:#0d1117;color:#c9d1d9;font:14px system-ui}main{display:flex;gap:18px;padding:16px;flex-wrap:wrap}.view{flex:1;min-width:280px}img{width:100%;height:auto;border-radius:8px}.panel{width:320px}h2{color:#58a6ff}button{display:block;width:100%;margin:12px 0;padding:12px;background:#238636;color:white;border:0;border-radius:6px;cursor:pointer}button:disabled{opacity:.5}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#161b22;padding:10px;max-height:280px;overflow:auto}.note{color:#f0c674}a{color:#58a6ff}</style>
<main><section class="view"><h2>Vision SDK 原始画面</h2><img src="/video_feed"><p>保持原始 640×480 比例；不打开 USB/UVC 或 CAN。</p><h3>最近一次采样标记</h3><img id="overlay" hidden></section>
<section class="panel"><h2>手眼标定 · 只读采样</h2><p>ChArUco 9×12 · 方格 15 mm · 标记 11.25 mm · DICT_5X5_100</p><p class="note">标定板固定在桌面。通过原控制页手动调整安全姿态，静止后采样；此页不发运动或夹爪命令。</p>
<a href="http://192.168.58.68:9983/" target="_blank" rel="noopener">打开原机械臂控制页</a>
<pre id="state">等待端口反馈…</pre><button id="capture" onclick="act('capture')">采集当前姿态 + 标定板</button>
<button id="compute" disabled onclick="act('compute')">计算候选标定（至少 15 组）</button>
<pre id="message">先把完整标定板放入视野，至少 20 个标记、30 个角点。采集不同旋转方向和不同画面位置，避免重复姿态。</pre>
<pre id="result">结果仅为候选，物理批准仍 pending；不会自动替换现有标定。</pre>
<a href="/result.json" target="_blank">查看候选结果 JSON</a>
<p class="note">内参从当前 SDK 图像估计，不沿用旧脚本的错误内参。需多个旋转轴和足够画面覆盖；残差超过阈值时拒绝求解。求解通过也不等于实机路径验证通过。</p></section></main>
<script>const token='TOKEN';async function poll(){try{let d=await(await fetch('/status')).json();document.getElementById('state').textContent=JSON.stringify(d,null,2);document.getElementById('compute').disabled=d.pairs<15;document.getElementById('capture').disabled=!d.robot_stationary;}catch(e){document.getElementById('state').textContent='状态连接失败: '+e.message;}}
async function act(name){document.getElementById(name).disabled=true;document.getElementById('message').textContent='处理中…';try{let r=await fetch('/'+name,{method:'POST',headers:{'X-Calibration-Token':token}});let d=await r.json();document.getElementById('message').textContent=JSON.stringify(d,null,2);if(d.ok&&name==='capture'){let i=document.getElementById('overlay');i.hidden=false;i.src='/overlay.jpg?t='+Date.now();}if(d.ok&&name==='compute')document.getElementById('result').textContent=JSON.stringify(d.result,null,2);}catch(e){document.getElementById('message').textContent=e.message;}finally{await poll();}}setInterval(poll,1000);poll();</script></html>'''


def main():
    root=Path(os.environ['HANDEYE_SESSION_DIR'])
    session=CalibrationSession(root)
    token=secrets.token_urlsafe(32)
    states=collections.deque(maxlen=300);state_lock=threading.Lock();operation_lock=threading.Lock()
    node=str(LIVE/'local/runtimes/node/bin/node')
    env=dict(os.environ,NODE_PATH=str(LIVE/'services/robot/node_modules'))
    def consume():
        previous=-1
        try:
            for line in reader.stdout:
                try:
                    state=json.loads(line)
                    with state_lock:
                        sequence=state.get('state_sequence')
                        if type(sequence) is not int:
                            states.clear();previous=-1
                        elif sequence<=previous:
                            states.clear()
                            continue
                        else:previous=sequence
                        states.append(state)
                except (ValueError,TypeError):
                    with state_lock:states.clear()
        finally:
            with state_lock:states.clear()
    class Handler(BaseHTTPRequestHandler):
        def send(self,data,status=200,kind='application/json'):
            body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode() if kind=='application/json' else data
            self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8' if kind.startswith('text/') else kind)
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
        def do_GET(self):
            path=self.path.split('?')[0]
            if path=='/':return self.send(HTML.replace('TOKEN',token).encode(),kind='text/html')
            if path=='/status':
                with state_lock:latest=dict(states[-1]) if states else {}
                valid=validate_state(latest,time.monotonic_ns())
                return self.send({'pairs':len(session.samples),'robot_stationary':bool(valid),'read_only':True,
                                  'robot_source':ROBOT,'camera_source':VISION,'camera_serial':SERIAL,
                                  'state_sequence':latest.get('state_sequence'),'flange_position_m':latest.get('flange_position_m'),
                                  'flange_euler_rad':latest.get('flange_euler_rad'),'physical_validation':'pending',
                                  'session_dir':str(root)})
            if path=='/result.json':return self.send(session.result or {'error':'no_candidate_yet'},200 if session.result else 404)
            if path=='/overlay.jpg':return self.send(session.overlay or b'',200 if session.overlay else 404,'image/jpeg')
            if path=='/video_feed':
                try:
                    with urllib.request.urlopen(VISION+'/camera/xvisio/raw',timeout=5) as upstream:
                        self.send_response(200);self.send_header('Content-Type',upstream.headers['Content-Type'])
                        self.send_header('Cache-Control','no-store');self.end_headers()
                        while True:
                            block=upstream.read(8192)
                            if not block:break
                            self.wfile.write(block);self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError):pass
                except Exception as e:self.log_error('vision_stream: %s',e)
                return
            self.send({'error':'not_found'},404)
        def do_POST(self):
            origin=self.headers.get('Origin')
            if self.headers.get('X-Calibration-Token')!=token or (origin and origin!='http://'+self.headers.get('Host','')):
                return self.send({'error':'same_origin_token_required'},403)
            if self.path not in ['/capture','/compute']:return self.send({'error':'not_found'},404)
            if not operation_lock.acquire(blocking=False):return self.send({'error':'operation_in_progress'},409)
            try:
                if self.path=='/capture':
                    with urllib.request.urlopen(VISION+'/api/vision/raw-frame/export',timeout=10) as response:
                        content=response.read(12*1024*1024+1)
                    if len(content)>12*1024*1024:raise ValueError('frame_too_large')
                    with np.load(io.BytesIO(content),allow_pickle=False) as bundle:
                        data={'rgb':bundle['rgb'].copy(),'metadata':json.loads(str(bundle['metadata_json']))}
                    for _ in range(20):
                        with state_lock:history=list(states)
                        if any(type(s.get('producer_monotonic_ns')) is int and
                               s['producer_monotonic_ns']>=data['metadata']['monotonic_ns'] for s in history):break
                        time.sleep(.01)
                    result=session.capture(data,history,time.monotonic_ns())
                    self.send({'ok':True,**result})
                else:self.send({'ok':True,'result':session.compute()})
            except Exception as e:self.send({'ok':False,'error':str(e)},422)
            finally:operation_lock.release()
    server=ThreadingHTTPServer(('0.0.0.0',8089),Handler)
    reader=subprocess.Popen([node,str(Path(__file__).with_name('robot_reader.js')),ROBOT],stdout=subprocess.PIPE,
                            text=True,env=env,bufsize=1)
    threading.Thread(target=consume,daemon=True).start()
    print(json.dumps({'service':'port-fed-handeye','port':8089,'readOnlyRobot':True,'sessionDir':str(root)}),flush=True)
    try:server.serve_forever()
    finally:server.server_close();reader.terminate();reader.wait(timeout=5)

if __name__=='__main__':main()
