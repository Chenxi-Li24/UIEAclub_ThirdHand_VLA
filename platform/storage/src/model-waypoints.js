'use strict';
const {transaction}=require('./pool');
const {identityError}=require('../../identity/src/errors');
const MODEL_VERSION='startouch-v3-model-v1',KIND='model_waypoint',MAX_WAYPOINTS=100;
const LIMITS=[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]];
const uuid=value=>typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(value);
function validatePose({joints,gripper}={}){
  if(!Array.isArray(joints)||joints.length!==6||Array.from(joints).some((n,i)=>!Number.isFinite(n)||n<LIMITS[i][0]||n>LIMITS[i][1])||!Number.isFinite(gripper)||gripper<0||gripper>1)throw identityError('INVALID_INPUT');
  return {joints:[...joints],gripper};
}
function owner(principal){if(!uuid(principal?.userId))throw identityError('UNAUTHENTICATED');return principal.userId;}
function item(row){
  const base={id:row.id,name:row.name,updatedAt:new Date(row.updated_at).toISOString(),source:'model',modelVersion:row.model_version};
  try{
    const p=row.program;
    if(row.model_version!==MODEL_VERSION||!p||p.kind!==KIND||p.version!==1||p.source!=='model'||p.unit!=='deg'||Object.keys(p).sort().join(',')!=='gripper,joints,kind,source,unit,version')throw Error('Unsupported waypoint');
    return {...base,available:true,...validatePose(p)};
  }catch{return {...base,available:false};}
}
function createModelWaypoints({pool}){
  return {
    async list({principal}){
      const result=await pool.query(`SELECT id,name,model_version,program,updated_at FROM simulation.user_programs
        WHERE user_id=$1 AND program->>'kind'=$2 ORDER BY updated_at DESC,id DESC LIMIT 101`,[owner(principal),KIND]);
      if(result.rows.length>MAX_WAYPOINTS)throw identityError('WAYPOINT_LIMIT_REACHED');
      return {waypoints:result.rows.map(item),limit:MAX_WAYPOINTS};
    },
    async save({principal,name,...input}){
      const userId=owner(principal),pose=validatePose(input);
      if(typeof name!=='string'||![...name.trim()].length||[...name.trim()].length>120)throw identityError('INVALID_INPUT');
      return transaction(pool,async client=>{
        const user=(await client.query("SELECT id FROM auth.users WHERE id=$1 AND status='active' FOR UPDATE",[userId])).rows[0];
        if(!user)throw identityError('FORBIDDEN');
        const count=(await client.query("SELECT count(*)::int AS count FROM simulation.user_programs WHERE user_id=$1 AND program->>'kind'=$2",[userId,KIND])).rows[0].count;
        if(count>=MAX_WAYPOINTS)throw identityError('WAYPOINT_LIMIT_REACHED');
        const row=(await client.query(`INSERT INTO simulation.user_programs(user_id,name,model_version,program)
          VALUES($1,$2,$3,$4) RETURNING id,name,model_version,program,updated_at`,[userId,name.trim(),MODEL_VERSION,{kind:KIND,version:1,source:'model',unit:'deg',...pose}])).rows[0];
        return item(row);
      });
    },
    async remove({principal,id}){
      const userId=owner(principal);if(!uuid(id))throw identityError('INVALID_INPUT');
      const result=await pool.query("DELETE FROM simulation.user_programs WHERE id=$1 AND user_id=$2 AND program->>'kind'=$3 RETURNING id",[id,userId,KIND]);
      if(!result.rowCount)throw identityError('NOT_FOUND');return {deleted:true,id};
    }
  };
}
module.exports={createModelWaypoints,validatePose,MODEL_VERSION,MAX_WAYPOINTS};
