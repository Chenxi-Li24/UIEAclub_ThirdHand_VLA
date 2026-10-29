'use strict';
(function(root,factory){
  const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.ThirdHandCameraLighting=api;
})(typeof globalThis==='undefined'?null:globalThis,()=>{
  const rigs=new WeakMap();
  function sceneBackground(THREE,style){
    const value=style?.getPropertyValue('--bg-primary')?.trim();
    return new THREE.Color(value||'#ffffff');
  }
  function installCameraLighting(THREE,scene,camera){
    if(rigs.has(camera))return rigs.get(camera);
    const group=new THREE.Group();group.name='thirdhand-camera-light-rig';
    const target=new THREE.Object3D();target.position.set(0,0,-1000);group.add(target);
    const key=new THREE.DirectionalLight(0xffffff,1.15);
    key.position.set(-350,450,200);key.target=target;
    key.castShadow=true;key.shadow.mapSize.set(2048,2048);
    Object.assign(key.shadow.camera,{left:-1400,right:1400,top:1400,bottom:-1400,near:1,far:6000});
    key.shadow.camera.updateProjectionMatrix();key.shadow.bias=-0.0002;key.shadow.normalBias=.8;
    const fill=new THREE.DirectionalLight(0xffffff,.55);
    fill.position.set(420,100,150);fill.target=target;
    group.add(key,fill);camera.add(group);if(!camera.parent)scene.add(camera);
    const ground=new THREE.Mesh(new THREE.PlaneGeometry(4000,4000),new THREE.ShadowMaterial({color:0x28313c,opacity:.23}));
    ground.name='thirdhand-shadow-ground';ground.rotation.x=-Math.PI/2;ground.position.y=-1;ground.receiveShadow=true;scene.add(ground);
    const rig=Object.freeze({group,key,fill,target,ground});rigs.set(camera,rig);return rig;
  }
  function configureModelMaterials(loader){
    const loadMesh=loader.loadMeshCb.bind(loader);
    loader.loadMeshCb=(url,manager,done)=>loadMesh(url,manager,(object,error)=>{
      // URDFLoader assigns its material inside done(), after the URDF promise resolves.
      done(object,error);
      object?.traverse(mesh=>{
        if(!mesh.isMesh)return;
        const materials=Array.isArray(mesh.material)?mesh.material:[mesh.material];
        materials.forEach(material=>material?.color?.setHex(0x89929d));
        mesh.castShadow=true;mesh.receiveShadow=true;
      });
    });
  }
  function frameCamera(THREE,camera,controls,object){
    const box=new THREE.Box3().setFromObject(object);
    if(box.isEmpty())return false;
    const sphere=box.getBoundingSphere(new THREE.Sphere());
    const vertical=THREE.MathUtils.degToRad(camera.fov)/2;
    const halfAngle=Math.min(vertical,Math.atan(Math.tan(vertical)*camera.aspect));
    const distance=Math.max(controls?.minDistance||0,sphere.radius/Math.sin(halfAngle)*1.12);
    const direction=camera.position.clone().sub(controls?.target||sphere.center).normalize();
    if(direction.lengthSq()===0)direction.set(1,.7,1).normalize();
    camera.position.copy(sphere.center).addScaledVector(direction,distance);
    camera.lookAt(sphere.center);
    if(controls){controls.target.copy(sphere.center);controls.maxDistance=Math.max(controls.maxDistance||0,distance*2);controls.update();}
    return true;
  }
  return {sceneBackground,installCameraLighting,configureModelMaterials,frameCamera};
});
