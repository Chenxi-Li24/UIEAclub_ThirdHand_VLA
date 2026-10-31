'use strict';
// Lossless Meshopt buffer compression: no simplification, filters or reordering.
const fs=require('node:fs'),path=require('node:path'),{createHash}=require('node:crypto'),{gzipSync}=require('node:zlib');
const {MeshoptEncoder,MeshoptDecoder}=require('meshoptimizer');
async function pack(directory=path.resolve(__dirname,'../../assets/robot/startouch-v3/web')){
  await Promise.all([MeshoptEncoder.ready,MeshoptDecoder.ready]);
  const file=path.join(directory,'robot-visuals.glb'),raw=fs.readFileSync(file),length=raw.readUInt32LE(12);
  if(raw.toString('ascii',0,4)!=='glTF'||raw.readUInt32LE(8)!==raw.length)throw Error('Invalid source GLB');
  const model=JSON.parse(raw.toString('utf8',20,20+length)),binary=raw.subarray(28+length);
  if(model.extensionsRequired?.length)throw Error('Run build_web_robot.py before compressing');
  let offset=0;const chunks=[];
  for(const view of model.bufferViews){
    const accessor=model.accessors.find(value=>value.bufferView===model.bufferViews.indexOf(view));
    const mode=view.target===34962?'ATTRIBUTES':'INDICES',stride=view.byteStride||(accessor.componentType===5123?2:4),count=view.byteLength/stride;
    const original=binary.subarray(view.byteOffset,view.byteOffset+view.byteLength);
    const encoded=Buffer.from(MeshoptEncoder.encodeGltfBuffer(original,count,stride,mode));
    const decoded=new Uint8Array(view.byteLength);MeshoptDecoder.decodeGltfBuffer(decoded,count,stride,encoded,mode,'NONE');
    if(!Buffer.from(decoded).equals(original))throw Error('Lossless buffer round trip failed');
    view.buffer=1;view.extensions={EXT_meshopt_compression:{buffer:0,byteOffset:offset,byteLength:encoded.length,byteStride:stride,count,mode,filter:'NONE'}};
    chunks.push(encoded,Buffer.alloc((-encoded.length)&3));offset+=encoded.length+((-encoded.length)&3);
  }
  model.buffers=[{byteLength:offset},{byteLength:binary.length,extensions:{EXT_meshopt_compression:{fallback:true}}}];
  model.extensionsUsed=model.extensionsRequired=['EXT_meshopt_compression'];
  const json=Buffer.from(JSON.stringify(model)),metadata=Buffer.concat([json,Buffer.alloc((-json.length)&3,0x20)]),blob=Buffer.concat(chunks);
  const header=Buffer.alloc(20);header.write('glTF');header.writeUInt32LE(2,4);header.writeUInt32LE(28+metadata.length+blob.length,8);header.writeUInt32LE(metadata.length,12);header.write('JSON',16);
  const binHeader=Buffer.alloc(8);binHeader.writeUInt32LE(blob.length);binHeader.write('BIN\0',4);
  const result=Buffer.concat([header,metadata,binHeader,blob]),compressed=gzipSync(result,{level:3});
  const report=JSON.parse(fs.readFileSync(path.join(directory,'build-report.json'),'utf8'));
  Object.assign(report,{method:report.method+'+meshopt-0.22.0',meshoptFilters:'NONE',unpackedGlbBytes:raw.length,
    buffersVerifiedByteForByte:model.bufferViews.length,glbBytes:result.length,glbGzipLevel3Bytes:compressed.length,
    glbSha256:createHash('sha256').update(result).digest('hex')});
  fs.writeFileSync(file,result);fs.writeFileSync(file+'.gz',compressed);fs.writeFileSync(path.join(directory,'build-report.json'),JSON.stringify(report,null,2)+'\n');
  return report;
}
if(require.main===module)pack().then(report=>console.log(JSON.stringify(Object.fromEntries(Object.entries(report).filter(([key])=>key!=='meshes'))))).catch(error=>{console.error(error);process.exitCode=1;});
module.exports={pack};
