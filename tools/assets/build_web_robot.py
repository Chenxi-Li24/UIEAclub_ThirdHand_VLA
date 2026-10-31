"""Losslessly index the nine STL visual meshes into one website-only glTF 2 GLB.

No decimation, quantization, coordinate conversion or URDF edits. Face normals
are derived from the unchanged triangles by flat shading, not transported. Full
source STL remains canonical. Python standard library only, deterministic bytes.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
NAMES = ('base_link', 'link1', 'link2', 'link3', 'link4', 'link5',
         'gripper_base', 'gripper_link1', 'gripper_link2')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build(directory):
    blob = bytearray()
    model = {'asset': {'version': '2.0', 'generator': 'ThirdHand lossless STL indexing v1'},
             'scene': 0, 'scenes': [{'nodes': list(range(9))}], 'nodes': [], 'meshes': [],
             'accessors': [], 'bufferViews': [], 'buffers': []}
    report = {'format': 1, 'method': 'lossless-position-bitwise-indexing-with-flat-face-normals',
              'urdfSha256': sha((directory / 'FastTouchV3.SLDASM.urdf').read_bytes()), 'meshes': {}}
    for name in NAMES:
        raw = (directory / 'meshes' / (name + '.STL')).read_bytes()
        count = struct.unpack_from('<I', raw, 80)[0]
        if len(raw) != 84 + 50 * count:
            raise ValueError('Restored binary STL required: ' + name)
        vertices, indices, unique = bytearray(), [], {}
        bounds = [[float('inf')] * 3, [float('-inf')] * 3]
        attributes = hashlib.sha256()
        for face in range(count):
            at = 84 + face * 50
            normal = raw[at:at+12]
            for corner in range(3):
                position = raw[at+12+corner*12:at+24+corner*12]
                value = position
                attributes.update(value)
                if value not in unique:
                    unique[value] = len(unique)
                    vertices.extend(value)
                indices.append(unique[value])
                for axis, coordinate in enumerate(struct.unpack('<3f', position)):
                    bounds[0][axis] = min(bounds[0][axis], coordinate)
                    bounds[1][axis] = max(bounds[1][axis], coordinate)
        while len(blob) % 4:
            blob.append(0)
        vertex_view = len(model['bufferViews'])
        model['bufferViews'].append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(vertices),
                                     'byteStride': 12, 'target': 34962})
        blob.extend(vertices)
        offset = len(model['accessors'])
        model['accessors'].extend([
            {'bufferView': vertex_view, 'byteOffset': 0, 'componentType': 5126,
             'count': len(unique), 'type': 'VEC3', 'min': bounds[0], 'max': bounds[1]}])
        code, component = ('H', 5123) if len(unique) <= 65536 else ('I', 5125)
        indexed = struct.pack('<' + str(len(indices)) + code, *indices)
        model['accessors'].append({'bufferView': len(model['bufferViews']), 'componentType': component,
                                   'count': len(indices), 'type': 'SCALAR'})
        model['bufferViews'].append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(indexed), 'target': 34963})
        blob.extend(indexed)
        model['nodes'].append({'name': name, 'mesh': len(model['meshes'])})
        model['meshes'].append({'name': name, 'primitives': [{'attributes': {'POSITION': offset},
                                                            'indices': offset+1, 'mode': 4}]})
        report['meshes'][name] = {'sourceBytes': len(raw), 'sourceSha256': sha(raw), 'triangles': count,
                                  'vertices': len(unique), 'expandedPositionsSha256': attributes.hexdigest(),
                                  'bounds': bounds}
    while len(blob) % 4:
        blob.append(0)
    model['buffers'] = [{'byteLength': len(blob)}]
    metadata = json.dumps(model, sort_keys=True, separators=(',', ':')).encode()
    metadata += b' ' * (-len(metadata) % 4)
    result = struct.pack('<4sII', b'glTF', 2, 28+len(metadata)+len(blob))
    result += struct.pack('<I4s', len(metadata), b'JSON') + metadata
    result += struct.pack('<I4s', len(blob), b'BIN\0') + blob
    report.update({'glbBytes': len(result), 'glbGzipLevel3Bytes': len(gzip.compress(result, compresslevel=3, mtime=0)),
                   'glbSha256': sha(result), 'sourceBytes': sum(m['sourceBytes'] for m in report['meshes'].values()),
                   'triangles': sum(m['triangles'] for m in report['meshes'].values())})
    return result, report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT/'assets/robot/startouch-v3')
    args = parser.parse_args()
    data, summary = build(args.directory)
    destination = args.directory/'web'
    destination.mkdir(exist_ok=True)
    (destination/'robot-visuals.glb').write_bytes(data)
    (destination/'robot-visuals.glb.gz').write_bytes(gzip.compress(data, compresslevel=3, mtime=0))
    (destination/'build-report.json').write_text(json.dumps(summary, indent=2, sort_keys=True)+'\n', encoding='utf8', newline='\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'meshes'}, sort_keys=True))
