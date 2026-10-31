'use strict';
// Stable spreadsheet columns. Preserve the full operational record separately.
function csvCell(value){
  if(value===null||value===undefined)return '""';
  const numeric=typeof value==='number'&&Number.isFinite(value);
  const text=typeof value==='string'?value:JSON.stringify(value);
  return '"'+(!numeric&&/^[\s]*[=+\-@]|^[\t\r\n]/.test(text)?"'"+text:text).replaceAll('"','""')+'"';
}
const direct=name=>[name,row=>row[name]];
function sampleColumns(){
  const columns=['captured_at','received_at','device_id','boot_id','sample_seq'].map(direct);
  columns.push(['source_mode',row=>row.extra?.sourceMode],...['sdk_connected','moving'].map(direct));
  for(const [field,label,scale]of [['joint_position_rad','position_deg',180/Math.PI],['joint_velocity_rad_s','velocity_deg_s',180/Math.PI],['joint_current_a','current_a',1],['joint_torque_nm','torque_nm',1],['joint_temperature_c','temperature_c',1]]){
    for(let i=0;i<6;i++)columns.push([`j${i+1}_${label}`,row=>typeof row[field]?.[i]==='number'?row[field][i]*scale:null]);
  }
  for(const [field,names]of [['tcp_position_m',['tcp_x_m','tcp_y_m','tcp_z_m']],['tcp_orientation_xyzw',['tcp_qx','tcp_qy','tcp_qz','tcp_qw']]])names.forEach((name,i)=>columns.push([name,row=>row[field]?.[i]]));
  columns.push(...['tcp_frame_id','tool_version','calibration_version','gripper','clock_quality','state_age_ms','quality_flags','field_availability'].map(direct));
  return columns;
}
const fields={
  runs:['id','device_id','boot_id','started_at','ended_at','source','status','actor_display_name','actor_kind','versions'],
  commands:['command_id','device_id','boot_id','created_at','opcode','state','parameters','result','run_id','executor_epoch','sequence'],
  command_events:['id','command_id','captured_at','received_at','event_code','details'],
  device_events:['id','device_id','boot_id','captured_at','received_at','event_code','level','details'],
  invalid_samples:['id','device_id','boot_id','received_at','stream_kind','sample_seq','reason_code','sanitized_fields'],
  raw_batches:['id','device_id','boot_id','completed_at','stream_kind','batch_seq','first_seq','last_seq','row_count','digest','payload_base64'],
};
function operationalColumns(kind){
  const columns=kind==='samples'?sampleColumns():(fields[kind]||[]).map(direct);
  if(!columns.length)throw Error('Unsupported export kind');
  return [...columns,['record_json',row=>row]];
}
const memberColumns=[['id','id'],['username','username'],['display_name','displayName'],['email','email'],['organization','organization'],['role','role'],['status','status'],['locale','locale'],['registered_at_utc','createdAt'],['email_verified_at_utc','emailVerifiedAt']].map(([name,key])=>[name,row=>row[key] instanceof Date?row[key].toISOString():row[key]]);
const csvHeader=columns=>'\uFEFF'+columns.map(([name])=>csvCell(name)).join(',')+'\r\n';
const csvRow=(columns,row)=>columns.map(([,read])=>csvCell(read(row))).join(',')+'\r\n';
module.exports={csvCell,csvHeader,csvRow,operationalColumns,memberColumns};
