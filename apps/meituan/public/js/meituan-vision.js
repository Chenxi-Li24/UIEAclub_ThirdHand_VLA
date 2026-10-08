const STORAGE_KEY='thirdhand.meituan.battery.v1';
const COLOR_NAMES={red:'红色',yellow:'黄色',blue:'蓝色',green:'绿色',unknown:'颜色未知'};

export class BatteryVisionUI {
  constructor(root=document,options={}) {
    this.root=root;
    this.WebSocketClass=options.WebSocketClass||globalThis.WebSocket;
    this.location=options.location||globalThis.location;
    try {this.storage=options.storage||globalThis.localStorage;}catch {this.storage=null;}
    this.defaults={prompt:'battery .',boxThreshold:.3,textThreshold:.25};
    this.state='stopped';this.available=false;this.opened=false;this.mode='raw';this.socket=null;this.logs=[];
    const get=id=>root.getElementById(id);
    this.startButton=get('meituan-vision-start');this.stopButton=get('meituan-vision-stop');
    this.applyButton=get('meituan-vision-apply');this.resetButton=get('meituan-vision-reset');
    this.prompt=get('meituan-vision-prompt');this.box=get('meituan-vision-box');this.text=get('meituan-vision-text');
    this.stateLabel=get('meituan-vision-state');this.logView=get('meituan-vision-log');this.logDetails=get('meituan-vision-logs');
    this.camera=get('meituan-camera');this.cameraStatus=get('meituan-camera-status');this.detections=get('meituan-detections');
  }
  init() {
    this.startButton?.addEventListener('click',()=>this.start());
    this.stopButton?.addEventListener('click',()=>this.stop());
    this.applyButton?.addEventListener('click',()=>this.apply());
    this.resetButton?.addEventListener('click',()=>this.reset());
    let saved;
    try {saved=JSON.parse(this.storage?.getItem(STORAGE_KEY)||'null');}catch {}
    try {this.fill(saved?this.validate(saved):this.defaults);}catch {this.fill(this.defaults);}
    this.render();
  }
  fill(params) {
    this.prompt.value=params.prompt;
    this.box.value=String(params.boxThreshold);this.text.value=String(params.textThreshold);
  }
  validate(params) {
    if(!params||typeof params.prompt!=='string'||!params.prompt.trim()||params.prompt.trim().length>512)
      throw new Error('提示词须为1–512字符');
    for(const key of ['boxThreshold','textThreshold'])
      if(typeof params[key]!=='number'||!Number.isFinite(params[key])||params[key]<=0||params[key]>1)
        throw new Error('阈值须为大于0且不超过1的数值');
    return {prompt:params.prompt.trim(),boxThreshold:params.boxThreshold,textThreshold:params.textThreshold};
  }
  read() {
    return this.validate({prompt:this.prompt.value,boxThreshold:Number(this.box.value),textThreshold:Number(this.text.value)});
  }
  persist(params) {
    try {this.storage?.setItem(STORAGE_KEY,JSON.stringify(params));}
    catch(error){this.log({level:'warning',message:'浏览器未能保存参数：'+error.message});}
  }
  open() {
    this.opened=true;
    if(this.socket)return;
    const url=new URL('/ws',this.location.href);
    url.port='1035';url.protocol=this.location.protocol==='https:'?'wss:':'ws:';
    const socket=new this.WebSocketClass(url.href);
    this.socket=socket;
    socket.onmessage=event=>{
      if(!this.opened||this.socket!==socket)return;
      try {this.message(JSON.parse(event.data));}
      catch(error){this.log({level:'error',message:error.message});}
    };
    socket.onerror=()=>{
      if(this.socket===socket)this.log({level:'error',message:'1035识别控制未接通；原始视频可继续观看'});
    };
    socket.onclose=()=>{
      if(this.socket!==socket)return;
      this.socket=null;this.available=false;this.state='stopped';
      this.log({level:'warning',message:'识别控制连接断开，后台停止提交电池请求'});this.render();
    };
  }
  send(type,parameters) {
    if(this.socket?.readyState!==1)throw new Error('1035识别控制尚未连接');
    this.socket.send(JSON.stringify({type,...(parameters?{parameters}:{})}));
  }
  start() {
    try {const params=this.read();this.send('start',params);this.persist(params);}
    catch(error){this.log({level:'error',message:error.message});}
  }
  apply() {
    try {const params=this.read();if(this.state==='running')this.send('configure',params);this.persist(params);
      this.log({level:'info',message:'电池参数已应用；不修改瓶子配置',parameters:params});}
    catch(error){this.log({level:'error',message:error.message});}
  }
  reset() {this.fill(this.defaults);this.apply();}
  stop() {
    if(this.socket?.readyState===1)this.socket.send(JSON.stringify({type:'stop'}));
    this.state='stopped';this.render();
  }
  close() {
    this.opened=false;this.stop();
    const socket=this.socket;this.socket=null;this.available=false;
    socket?.close();this.render();
  }
  setMode(mode) {this.mode=mode;this.render();}
  stream() {
    if(this.mode!=='recognition')return;
    this.camera.hidden=this.state!=='running';
    if(this.state!=='running'){
      this.camera.removeAttribute('src');
      this.cameraStatus.textContent='识别已停止；点击“开始识别”';
      return;
    }
    const url=new URL('/camera/xvisio/vision',this.location.href);url.port='1035';
    if(this.camera.dataset.streamUrl!==url.href || !this.camera.src){
      this.camera.dataset.streamUrl=url.href;this.camera.src=url.href;
    }
    this.cameraStatus.textContent='电池识别中';
  }
  message(value) {
    if(value.type==='battery.status'){
      this.state=value.state;this.available=value.available===true;
      if(value.defaults)this.defaults=this.validate(value.defaults);
      for(const entry of value.logs||[])this.log(entry);
      this.render();
    }else if(value.type==='battery.result'&&this.state==='running'){
      this.detections.textContent=(value.detections||[]).map(item=>
        '#'+item.id+' '+(COLOR_NAMES[item.color]||'颜色未知')+
        ' · 检测 '+Math.round(item.score*100)+'%'+
        (Number.isFinite(item.colorScore)?' · 判色占比 '+Math.round(item.colorScore*100)+'%':'')).join('\n')||
        '本帧未检测到电池';
      this.cameraStatus.textContent='帧 '+value.frameId+' · '+(value.elapsedMs??'—')+' ms';
    }else if(value.type==='battery.log'){
      this.log(value.entry);
    }else if(value.type==='battery.error'){
      if(['inference_failed','inference_timeout','shared_hook_unavailable','camera_command_failed','invalid_result'].includes(value.code))
        this.state='error';
      this.log({level:'error',code:value.code,error:value.error});this.render();
    }
  }
  log(entry) {
    this.logs.push({timestamp:Date.now(),...entry});
    if(this.logs.length>200)this.logs.shift();
    this.logView.textContent=this.logs.map(value=>JSON.stringify(value,null,2)).join('\n\n');
    if(entry.level==='error')this.logDetails.open=true;
  }
  render() {
    this.startButton.disabled=!this.available||this.state==='running';
    this.stopButton.disabled=this.state!=='running';
    this.stateLabel.textContent=this.state==='running'?'识别中':this.state==='error'?'识别错误，查看日志':'识别已停止';
    this.stream();
  }
}
