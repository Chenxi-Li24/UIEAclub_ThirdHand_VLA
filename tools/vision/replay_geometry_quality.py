"""Read-only replay of captured XYZ/masks; no robot or camera connections."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import numpy as np
from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import RgbdFrame, MaskCandidate
from geometry_quality import estimate_grasp_candidates, GeometryRejected
from camera_bridge_with_quality import attach_depth_evidence

root=Path(sys.argv[1])
live=Path(sys.argv[2])
config=VisionConfig.from_yaml(live/'skills/manipulation/bottlegrasp/configs/vision.yaml')
upright=np.asarray(json.loads((root/'analysis.json').read_text())['upright_camera'])
rows=[]
for p in sorted(root.glob('frame-*.npz')):
    with np.load(p,allow_pickle=False) as data:
        mask=data['mask']
        frame=RgbdFrame(sequence=len(rows)+1,monotonic_ns=100+len(rows),camera_serial='replay',
                       rgb=data['rgb'],depth_m=data['depth_m'],xyz_camera_m=data['xyz_camera_m'])
        y,x=np.where(mask)
        candidate=MaskCandidate(1,'bottle',.99,(float(x.min()),float(y.min()),float(x.max()),float(y.max())),mask,True)
        target={'stable_id':1,'detection_id':1,'depth_valid':True,'blockers':[]}
        attach_depth_evidence({'targets':[target]},SimpleNamespace(tracks=[SimpleNamespace(candidate=candidate,state='confirmed')]),frame,config)
        row={'file':p.name,'depth':target}
        try:
            ranked=estimate_grasp_candidates(frame,candidate,config,upright_direction_camera=upright)
            pose=ranked[0].pose
            row.update(success=True,width_m=pose.width_m,height_m=pose.height_m)
        except GeometryRejected as error:row.update(success=False,reason=str(error))
        rows.append(row)
print(json.dumps({'passed':sum(r['success'] for r in rows),'total':len(rows),'rows':rows},indent=2))
