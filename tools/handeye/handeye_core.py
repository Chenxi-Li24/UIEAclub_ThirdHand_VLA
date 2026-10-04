"""Port-fed calibration math. No device, network, CAN or robot command ownership.

OpenCV hand-eye inputs/methods follow IFL-CAMP/easy_handeye's OpenCV backend.
This independently implemented adapter does not import ROS or vendor SDKs.
All outputs are candidates: numerical consistency is not physical approval.
"""
import math
import cv2
import numpy as np


def flange_transform(position, euler):
    p=np.asarray(position,float); rpy=np.asarray(euler,float)
    if p.shape!=(3,) or rpy.shape!=(3,) or not np.isfinite(p).all() or not np.isfinite(rpy).all():
        raise ValueError('invalid_flange_pose')
    r,pitch,y=rpy
    cr,sr=math.cos(r),math.sin(r); cp,sp=math.cos(pitch),math.sin(pitch); cy,sy=math.cos(y),math.sin(y)
    t=np.eye(4)
    t[:3,:3]=np.array([[cy,-sy,0],[sy,cy,0],[0,0,1]])@np.array([[cp,0,sp],[0,1,0],[-sp,0,cp]])@np.array([[1,0,0],[0,cr,-sr],[0,sr,cr]])
    t[:3,3]=position
    return t


def validate_state(s, now_ns):
    try:
        if (not isinstance(s,dict) or s.get('type')!='robot_state' or s.get('connected') is not True
            or s.get('healthy') is not True or s.get('moving') is not False or s.get('pose_frame')!='robot_flange'):
            return None
        for key in ['state_sequence','producer_monotonic_ns']:
            if type(s.get(key)) is not int or s[key]<0:return None
        if not 0<=now_ns-s['producer_monotonic_ns']<=500_000_000:return None
        for key,n in [('flange_position_m',3),('flange_euler_rad',3),('joints_deg',6),('velocities_deg_s',6)]:
            v=s.get(key)
            if not isinstance(v,list) or len(v)!=n or any(type(x) not in (int,float) or not math.isfinite(x) for x in v):return None
        if max(abs(x) for x in s['velocities_deg_s'])>2:return None
        return s
    except (TypeError,KeyError):return None


def match_state(states, frame_ns, now_ns):
    if type(frame_ns) is not int or not 0<=now_ns-frame_ns<=500_000_000:
        raise ValueError('camera_frame_stale')
    candidates=[s for s in states if type(s.get('producer_monotonic_ns')) is int]
    if not candidates:raise ValueError('robot_state_unavailable')
    before=[s for s in candidates if s['producer_monotonic_ns']<=frame_ns]
    after=[s for s in candidates if s['producer_monotonic_ns']>=frame_ns]
    if not before or not after:raise ValueError('need_stationary_feedback_bracketing_frame')
    left=max(before,key=lambda s:s['producer_monotonic_ns'])
    right=min(after,key=lambda s:s['producer_monotonic_ns'])
    if frame_ns-left['producer_monotonic_ns']>120_000_000 or right['producer_monotonic_ns']-frame_ns>120_000_000:
        raise ValueError('stationary_bracket_too_far_from_frame')
    left_index=next(i for i,s in enumerate(states) if s is left)
    right_index=next(i for i,s in enumerate(states) if s is right)
    if right_index<left_index:raise ValueError('reordered_robot_feedback')
    window=list(states)[left_index:]
    reference=flange_transform(left['flange_position_m'],left['flange_euler_rad']) if validate_state(left,now_ns) else None
    if reference is None:raise ValueError('invalid_stationary_bracket')
    for i,sample in enumerate(window):
        if validate_state(sample,now_ns) is None:raise ValueError('motion_or_invalid_feedback_during_capture')
        if i and (sample['state_sequence']<=window[i-1]['state_sequence'] or
                  sample['producer_monotonic_ns']<=window[i-1]['producer_monotonic_ns']):
            raise ValueError('replayed_robot_feedback')
        pose=flange_transform(sample['flange_position_m'],sample['flange_euler_rad'])
        angle=float(np.linalg.norm(cv2.Rodrigues(reference[:3,:3].T@pose[:3,:3])[0]))
        if np.linalg.norm(pose[:3,3]-reference[:3,3])>.002 or angle>math.radians(.5):
            raise ValueError('flange_drift_during_capture')
    s=min(candidates,key=lambda v:abs(v['producer_monotonic_ns']-frame_ns))
    if abs(s['producer_monotonic_ns']-frame_ns)>120_000_000 or validate_state(s,now_ns) is None:
        raise ValueError('no_synchronized_stationary_flange_state')
    return s


def _rigid(t):
    t=np.asarray(t,float)
    if (t.shape!=(4,4) or not np.isfinite(t).all() or not np.allclose(t[3],[0,0,0,1],atol=1e-8)
        or not np.allclose(t[:3,:3].T@t[:3,:3],np.eye(3),atol=1e-6)
        or not np.isclose(np.linalg.det(t[:3,:3]),1,atol=1e-6)):
        raise ValueError('non_rigid_transform')
    return t


def solve_handeye(pairs):
    if len(pairs)<15:raise ValueError('need_at_least_15_diverse_samples')
    pairs=[(_rigid(a),_rigid(b)) for a,b in pairs]
    rotation_vectors=np.array([cv2.Rodrigues(pairs[0][0][:3,:3].T@a[:3,:3])[0].ravel() for a,b in pairs])
    singular=np.linalg.svd(rotation_vectors,compute_uv=False)
    if singular[1]<.2:raise ValueError('insufficient_rotation_axis_diversity')
    training=[p for i,p in enumerate(pairs) if i%5!=0]
    held=[p for i,p in enumerate(pairs) if i%5==0]
    methods={'Tsai':cv2.CALIB_HAND_EYE_TSAI,'Park':cv2.CALIB_HAND_EYE_PARK,
             'Horaud':cv2.CALIB_HAND_EYE_HORAUD,'Andreff':cv2.CALIB_HAND_EYE_ANDREFF,
             'Daniilidis':cv2.CALIB_HAND_EYE_DANIILIDIS}
    results=[]
    for name,method in methods.items():
        try:
            rot,tr=cv2.calibrateHandEye([a[:3,:3] for a,b in training],[a[:3,3] for a,b in training],
                                       [b[:3,:3] for a,b in training],[b[:3,3] for a,b in training],method=method)
            x=np.eye(4);x[:3,:3]=rot;x[:3,3]=tr.ravel();x=_rigid(x)
            boards=[a@x@b for a,b in training]
            anchor=np.median(np.array([v[:3,3] for v in boards]),axis=0)
            all_errors=[float(np.linalg.norm((a@x@b)[:3,3]-anchor)) for a,b in pairs]
            errors=[float(np.linalg.norm((a@x@b)[:3,3]-anchor)) for a,b in held]
            reference=boards[0][:3,:3]
            degrees=[float(np.linalg.norm(cv2.Rodrigues(reference.T@(a@x@b)[:3,:3])[0])*180/math.pi) for a,b in held]
            results.append(dict(method=name,T_flange_camera=x.tolist(),held_out_max_translation_m=max(errors),
                                held_out_max_rotation_deg=max(degrees),all_translation_errors_m=all_errors))
        except (ValueError,cv2.error):continue
    if not results:raise ValueError('all_handeye_algorithms_failed')
    best=min(results,key=lambda x:x['held_out_max_translation_m'])
    return {**best,'algorithms':results,'training_count':len(training),'held_out_count':len(held),
            'numerically_validated':best['held_out_max_translation_m']<=.01 and best['held_out_max_rotation_deg']<=2,
            'approved_for_bottle_grasp':False,'physical_validation':'pending'}


def fit_camera(samples, size):
    """Fit the actual stream's fisheye intrinsics; never reuse mismatched K.

Training uses 4/5 poses; every fifth image is held out from intrinsic fitting.
The returned board poses are estimated with OpenCV from undistorted corners.
"""
    if len(samples)<15:raise ValueError('need_at_least_15_diverse_samples')
    objects=[np.asarray(s['object_points'],float).reshape(-1,1,3) for s in samples]
    images=[np.asarray(s['image_points'],float).reshape(-1,1,2) for s in samples]
    if any(len(o)<30 or len(o)!=len(v) or not np.isfinite(o).all() or not np.isfinite(v).all() for o,v in zip(objects,images)):
        raise ValueError('insufficient_or_invalid_board_corners')
    train=[i for i in range(len(samples)) if i%5!=0]
    k=np.array([[size[0]*.34,0,size[0]/2],[0,size[0]*.34,size[1]/2],[0,0,1]],float)
    d=np.zeros((4,1))
    flags=cv2.fisheye.CALIB_USE_INTRINSIC_GUESS|cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC|cv2.fisheye.CALIB_FIX_SKEW
    rms,k,d,_,_=cv2.fisheye.calibrate([objects[i] for i in train],[images[i] for i in train],size,k,d,flags=flags,
                                   criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,100,1e-9))
    if not np.isfinite(k).all() or not np.isfinite(d).all() or min(k[0,0],k[1,1])<=0:
        raise ValueError('camera_fit_invalid')
    transforms=[];errors=[]
    for obj,img in zip(objects,images):
        norm=cv2.fisheye.undistortPoints(img,k,d)
        ok,rv,tv=cv2.solvePnP(obj,norm,np.eye(3),None,flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok or tv[2,0]<=0:raise ValueError('board_pose_failed')
        predicted,_=cv2.fisheye.projectPoints(obj,rv,tv,k,d)
        err=float(np.sqrt(np.mean(np.sum((predicted-img)**2,axis=2))))
        t=np.eye(4);t[:3,:3]=cv2.Rodrigues(rv)[0];t[:3,3]=tv.ravel()
        transforms.append(t.tolist());errors.append(err)
    if max(errors)>1:raise ValueError(f'camera_reprojection_above_1px:{max(errors):.3f}')
    return {'model':'opencv_fisheye_fitted_from_same_sdk_stream','K':k.tolist(),'D':d.ravel().tolist(),
            'image_size':list(size),'training_rms_px':float(rms),'frame_rmse_px':errors,
            'held_out_image_indices':[i for i in range(len(samples)) if i%5==0], 'board_transforms':transforms}
