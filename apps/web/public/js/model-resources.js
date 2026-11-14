import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {MeshoptDecoder} from './lib/meshopt_decoder.module.js';
import './robot-viewer.js';
import './model-waypoints.js';
export function createViewer({assetBase,timeoutMs=15000,onProgress}){
  return globalThis.ThirdHandRobotViewer.createRobotViewer({THREE,OrbitControls,assetBase,loadVisualMeshes:async base=>{
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
    try{
      const result=await fetch(`${base}/models/startouch-v3/web/robot-visuals.glb?v=20261113c`,{credentials:'same-origin',signal:controller.signal});
      if(!result.ok)throw Error('Model download failed');
      let raw;
      if(onProgress && result.body){
        const reader=result.body.getReader(),chunks=[];let received=0;
        const total=Number(result.headers.get('content-length'))||0;
        while(true){const {done,value}=await reader.read();if(done)break;chunks.push(value);received+=value.length;onProgress(received,total);}
        const bytes=new Uint8Array(received);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}raw=bytes.buffer;
      }else raw=await result.arrayBuffer();
      const loader=new GLTFLoader();loader.setMeshoptDecoder(MeshoptDecoder);
      const gltf=await loader.parseAsync(raw,base+'/models/startouch-v3/web/');
      const meshes=new Map(gltf.scene.children.map(mesh=>[mesh.name,mesh]));
      for(const name of ['base_link','link1','link2','link3','link4','link5','gripper_base','gripper_link1','gripper_link2'])if(!meshes.get(name)?.isMesh)throw Error('Compact model is incomplete');
      return meshes;
    }finally{clearTimeout(timer);}
  }});
}
