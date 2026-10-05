"""Derive canonical flange calibration without mutating original evidence."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

def rigid(value):
    matrix=np.asarray(value,dtype=float)
    if (matrix.shape!=(4,4) or not np.isfinite(matrix).all() or
        not np.allclose(matrix[3],[0,0,0,1],atol=1e-9) or
        not np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3),atol=1e-6) or
        not np.isclose(np.linalg.det(matrix[:3,:3]),1,atol=1e-6)):
        raise ValueError('non_rigid_transform')
    return matrix

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--policy',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--samples',type=Path)
    args=parser.parse_args()
    raw=args.source.read_bytes();source=json.loads(raw)
    if source.get('frame_normalization'):raise ValueError('already_normalized')
    if (source.get('schema')!='thirdhand-handeye-calibration-v3' or
        source.get('robot_state_semantics')!='T_base_flange' or source.get('extrinsic_semantics')!='T_flange_camera'):
        raise ValueError('source_calibration_schema_mismatch')
    policy_raw=args.policy.read_bytes();policy=json.loads(policy_raw)
    if (policy.get('schema')!='thirdhand-robot-frame-policy-v1' or
        policy.get('source_semantics')!='sdk_tool_mislabeled_as_robot_flange' or
        policy.get('legacy_calibration_sha256')!=hashlib.sha256(raw).hexdigest()):
        raise ValueError('source_policy_mismatch')
    tool=rigid(policy['T_flange_sdk_tool']);old=rigid(source['T_flange_camera']['matrix_4x4'])
    converted=copy.deepcopy(source);converted['T_flange_camera']['matrix_4x4']=(tool@old).tolist()
    converted['frame_normalization']={'policy_id':'sha256:'+hashlib.sha256(policy_raw).hexdigest(),
        'source_calibration_sha256':hashlib.sha256(raw).hexdigest(),
        'source_extrinsic_semantics':'T_sdk_tool_camera','T_flange_sdk_tool':tool.tolist(),
        'note':'SDK configured tool frame is not a physically measured grasp TCP'}
    converted['approved_for_bottle_grasp']=False
    converted['physical_validation']['status']='pending'
    converted['physical_validation']['measured_error_m']=None
    converted['activated_camera_mount_id']=None;converted['camera_mount_id_activation']=False
    report={'schema':'thirdhand-frame-migration-report-v1','samples':0,'maximum_base_camera_delta':0.,'physical_approval':False}
    derived_samples=[]
    if args.samples:
        inverse=np.linalg.inv(tool)
        for sample in json.loads(args.samples.read_text()):
            if sample.get('frame_normalization'):raise ValueError('sample_already_normalized')
            sdk=rigid(sample['T_base_flange']);flange=sdk@inverse
            delta=float(np.max(np.abs(flange@(tool@old)-sdk@old)))
            if delta>1e-9:raise ValueError('base_camera_changed')
            derived=copy.deepcopy(sample)
            derived['legacy_T_base_sdk_tool']=sdk.tolist();derived['T_base_flange']=flange.tolist()
            # Robot state is preserved explicitly as legacy evidence, not re-labeled.
            derived['legacy_robot_state']=derived.pop('robot_state',None)
            derived['frame_normalization']=copy.deepcopy(converted['frame_normalization'])
            derived_samples.append(derived);report['samples']+=1
            report['maximum_base_camera_delta']=max(report['maximum_base_camera_delta'],delta)
    # A fresh output directory prevents accidental replacement or mixed datasets.
    args.output.mkdir(parents=True,exist_ok=False)
    for name,data in [('handeye-flange.json',converted),('report.json',report),('samples-flange.json',derived_samples)]:
        with (args.output/name).open('x') as f:json.dump(data,f,indent=2,allow_nan=False)
    print(json.dumps(report))

if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,TypeError,FileExistsError) as error:
        print(str(error),file=sys.stderr);sys.exit(1)
