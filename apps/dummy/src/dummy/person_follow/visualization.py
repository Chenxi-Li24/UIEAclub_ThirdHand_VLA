import time
import cv2

COLORS={"LOCKED":(70,255,70),"AMBIGUOUS":(0,180,255),"LOST":(0,0,255),"REACQUIRING":(255,180,0)}
def dashboard_snapshot(state,now=None):
    s=dict(state or {}); now=time.time() if now is None else now
    return {"timestamp":now,"vision":{k:s.get(k) for k in ("frame_id","fps","latency_ms","camera_view_id")},"identity":{k:s.get(k) for k in ("track_id","identity_id","identity_state","confidence")},"control":s.get("proposal") or {},"gateway":s.get("gateway") or {},"verification":s.get("verification") or {},"versions":{k:s.get(k) for k in ("model_id","model_sha256","calibration_hash")}}
def render_overlay(frame,state):
    out=frame.copy(); h,w=out.shape[:2]; cx,cy=w//2,h//2
    identity=state.get("identity_state","UNBOUND"); color=COLORS.get(identity,(180,180,180))
    cv2.drawMarker(out,(cx,cy),(255,255,255),cv2.MARKER_CROSS,28,1)
    box=state.get("bbox_xyxy"); center=state.get("center_px")
    if box:
        x1,y1,x2,y2=map(int,box); cv2.rectangle(out,(x1,y1),(x2,y2),color,2)
    if center:
        u,v=map(int,center); cv2.arrowedLine(out,(cx,cy),(u,v),color,2); cv2.circle(out,(u,v),5,color,-1)
    lines=[f"{identity} track={state.get('track_id','-')} id={str(state.get('identity_id','-'))[:8]} conf={state.get('confidence',0):.2f}",f"fps={state.get('fps',0):.1f} latency={state.get('latency_ms',0):.1f}ms frame={state.get('frame_id','-')}"]
    p=state.get("proposal") or {}; g=state.get("gateway") or {}; v=state.get("verification") or {}
    lines += [f"proposal={p.get('proposal_id','-')} joints={p.get('joints_deg','-')}",f"gateway={g.get('reason_code','-')} verify={v.get('reason_code','-')} improve={v.get('improvement_px','-')}",f"model={state.get('model_id','-')} cal={str(state.get('calibration_hash','-'))[:10]}"]
    cv2.rectangle(out,(6,6),(min(w-6,760),132),(0,0,0),-1)
    for i,line in enumerate(lines): cv2.putText(out,line,(14,28+i*23),cv2.FONT_HERSHEY_SIMPLEX,.55,color if i==0 else (230,230,230),1,cv2.LINE_AA)
    return out
