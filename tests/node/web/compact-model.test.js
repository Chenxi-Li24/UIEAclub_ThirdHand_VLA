'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),{createHash}=require('node:crypto'),{gunzipSync}=require('node:zlib');
const {MeshoptDecoder}=require('meshoptimizer');
const directory='assets/robot/startouch-v3',sha=raw=>createHash('sha256').update(raw).digest('hex');
test('compact website GLB restores every source triangle and position byte-for-byte with unchanged URDF and bounds',async()=>{
  await MeshoptDecoder.ready;
  const report=JSON.parse(fs.readFileSync(directory+'/web/build-report.json','utf8')),raw=fs.readFileSync(directory+'/web/robot-visuals.glb');
  assert.equal(raw.toString('ascii',0,4),'glTF','restore the web assets with Git LFS');
  assert.equal(sha(raw),report.glbSha256);assert.equal(sha(fs.readFileSync(directory+'/FastTouchV3.SLDASM.urdf')),report.urdfSha256);
  assert.deepEqual(gunzipSync(fs.readFileSync(directory+'/web/robot-visuals.glb.gz')),raw);
  assert.ok(report.glbGzipLevel3Bytes<2_000_000);assert.equal(report.triangles,448604);
  const length=raw.readUInt32LE(12),model=JSON.parse(raw.toString('utf8',20,20+length)),binary=raw.subarray(28+length),views=[];
  for(const view of model.bufferViews){
    const e=view.extensions.EXT_meshopt_compression;assert.equal(e.filter,'NONE');
    const decoded=new Uint8Array(view.byteLength);MeshoptDecoder.decodeGltfBuffer(decoded,e.count,e.byteStride,binary.subarray(e.byteOffset,e.byteOffset+e.byteLength),e.mode,e.filter);views.push(Buffer.from(decoded));
  }
  assert.equal(model.nodes.length,9);
  for(const node of model.nodes){
    assert.equal(node.translation,undefined);assert.equal(node.rotation,undefined);assert.equal(node.scale,undefined);
    const input=fs.readFileSync(`${directory}/meshes/${node.name}.STL`),source=report.meshes[node.name],primitive=model.meshes[node.mesh].primitives[0];
    assert.equal(sha(input),source.sourceSha256);
    const position=model.accessors[primitive.attributes.POSITION],index=model.accessors[primitive.indices],positions=views[position.bufferView],indices=views[index.bufferView];
    const original=Buffer.alloc(source.triangles*36),expanded=Buffer.alloc(original.length);
    for(let face=0;face<source.triangles;face++)input.copy(original,face*36,84+face*50+12,84+face*50+48);
    const stride=index.componentType===5123?2:4;
    for(let corner=0;corner<index.count;corner++){
      const vertex=stride===2?indices.readUInt16LE(corner*2):indices.readUInt32LE(corner*4);
      positions.copy(expanded,corner*12,vertex*12,vertex*12+12);
    }
    assert.deepEqual(expanded,original,node.name+' geometry changed');
    assert.equal(sha(expanded),source.expandedPositionsSha256);
    assert.deepEqual(position.min,source.bounds[0]);assert.deepEqual(position.max,source.bounds[1]);
  }
});
