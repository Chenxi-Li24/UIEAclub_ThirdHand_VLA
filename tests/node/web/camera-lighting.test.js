'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const file=path.resolve(__dirname,'../../../apps/web/public/js/camera-lighting.js');
const threeSource=fs.readFileSync(path.resolve(__dirname,'../../../apps/web/public/js/lib/three.module.js'),'utf8');
const three=import('data:text/javascript;base64,'+Buffer.from(threeSource).toString('base64'));
function api(){assert.ok(fs.existsSync(file),'camera-relative lighting implementation is missing');return require(file);}
test('view-space key and fill directions stay fixed when the orbit camera rotates',async()=>{
 const THREE=await three,{installCameraLighting}=api(),scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera();
 camera.position.set(600,400,600);camera.lookAt(0,200,0);
 const rig=installCameraLighting(THREE,scene,camera);
 const eyeDirection=light=>{scene.updateMatrixWorld(true);return light.target.getWorldPosition(new THREE.Vector3()).sub(light.getWorldPosition(new THREE.Vector3())).normalize().applyQuaternion(camera.getWorldQuaternion(new THREE.Quaternion()).invert());};
 const before=[eyeDirection(rig.key),eyeDirection(rig.fill)];
 const grid=new THREE.GridHelper(1200,24);scene.add(grid);grid.updateMatrixWorld(true);const fixed=grid.matrixWorld.clone();
 camera.position.set(-500,600,200);camera.lookAt(0,200,0);
 for(const [i,light]of [rig.key,rig.fill].entries())assert.ok(eyeDirection(light).distanceTo(before[i])<1e-10);
 assert.ok(grid.matrixWorld.equals(fixed),'orbiting must not rotate the world grid');
 assert.ok(eyeDirection(rig.key).z<0,'light must illuminate the scene in front of the camera');
});
test('installing the rig again does not duplicate lights',async()=>{
 const THREE=await three,{installCameraLighting}=api(),scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera();
 const first=installCameraLighting(THREE,scene,camera),second=installCameraLighting(THREE,scene,camera);
 assert.equal(second,first);assert.equal(camera.parent,scene);
});
test('view-fixed key light casts real shadows onto a transparent world-fixed floor',async()=>{
 const THREE=await three,scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera();
 const rig=api().installCameraLighting(THREE,scene,camera);
 assert.equal(rig.key.castShadow,true);assert.equal(rig.fill.castShadow,false);
 assert.ok(rig.key.shadow.mapSize.x>=1024);assert.ok(rig.key.shadow.camera.far>3000);
 assert.equal(rig.ground.receiveShadow,true);assert.equal(rig.ground.material.isShadowMaterial,true);
 assert.equal(rig.ground.parent,scene);assert.ok(rig.ground.position.y<0);
 rig.ground.updateMatrixWorld(true);const fixed=rig.ground.matrixWorld.clone();
 camera.position.set(-500,600,200);camera.lookAt(0,200,0);scene.updateMatrixWorld(true);
 assert.ok(rig.ground.matrixWorld.equals(fixed));
 assert.equal(api().installCameraLighting(THREE,scene,camera).ground,rig.ground);
});
test('computed theme background is used without requiring an inline CSS override',async()=>{
 const THREE=await three,{sceneBackground}=api();
 const white=sceneBackground(THREE,{getPropertyValue:()=> '#ffffff'});
 assert.equal(white.getHex(),0xffffff);
 assert.equal(sceneBackground(THREE,{getPropertyValue:()=> '  #f5f6f8  '}).getHex(),0xf5f6f8);
});
test('late URDF mesh completion keeps the requested gray material after loader assignment',async()=>{
 const THREE=await three,{configureModelMaterials}=api();let finish;
 const loader={loadMeshCb(_url,_manager,done){finish=done;}};
 configureModelMaterials(loader);
 const mesh=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshPhongMaterial());
 loader.loadMeshCb('mesh.stl',null,object=>{object.material=new THREE.MeshPhongMaterial({color:0xffffff});});
 finish(mesh,null);
 assert.equal(mesh.material.color.getHex(),0x89929d);
 assert.equal(mesh.castShadow,true);
});
test('framing keeps the whole model within narrow and wide viewports',async()=>{
 const THREE=await three,{frameCamera}=api();
 const model=new THREE.Mesh(new THREE.BoxGeometry(700,700,200));model.position.set(220,350,0);
 for(const aspect of [.6,3]){
   const camera=new THREE.PerspectiveCamera(50,aspect,1,5000);camera.position.set(600,400,600);
   const controls={target:new THREE.Vector3(),minDistance:200,update(){}};
   assert.equal(frameCamera(THREE,camera,controls,model),true);camera.updateMatrixWorld(true);
   const box=new THREE.Box3().setFromObject(model);
   for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){
     const point=new THREE.Vector3(x,y,z).project(camera);
     assert.ok(Math.abs(point.x)<1&&Math.abs(point.y)<1,'all corners must remain inside the viewport');
   }
 }
 assert.equal(frameCamera(THREE,new THREE.PerspectiveCamera(),null,new THREE.Group()),false);
});
