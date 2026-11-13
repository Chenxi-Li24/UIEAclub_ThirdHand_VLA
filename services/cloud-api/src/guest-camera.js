'use strict';
const {timingSafeEqual}=require('node:crypto');

// A separate, read-only public preview. Never grants identity or robot access.
function createGuestCamera({token=()=>process.env.GUEST_CAMERA_UPLOAD_TOKEN,now=Date.now,maxBytes=1024*1024,ttlMs=8000}={}){
 let frame=null,receivedAt=0;
 return async function serve(request,response,pathname){
  if(pathname!=='/guest-camera/frame')return false;
  const end=(status,body)=>{response.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});response.end(request.method==='HEAD'?undefined:JSON.stringify(body));};
  if(request.method==='POST'){
   const expected=token(),supplied=request.headers.authorization;
   if(!expected||typeof supplied!=='string'||Buffer.byteLength(supplied)!==Buffer.byteLength('Bearer '+expected)||!timingSafeEqual(Buffer.from(supplied),Buffer.from('Bearer '+expected))){end(403,{code:'UPLOAD_FORBIDDEN'});return true;}
   if(request.headers['content-type']!=='image/jpeg'){end(415,{code:'JPEG_REQUIRED'});return true;}
   const chunks=[];let size=0;
   try{for await(const chunk of request){size+=chunk.length;if(size>maxBytes){end(413,{code:'FRAME_TOO_LARGE'});return true;}chunks.push(chunk);}}catch{if(!response.headersSent)end(400,{code:'INCOMPLETE_FRAME'});return true;}
   const data=Buffer.concat(chunks);
   if(data.length<4||data[0]!==255||data[1]!==216||data.at(-2)!==255||data.at(-1)!==217){end(400,{code:'INVALID_JPEG'});return true;}
   frame=data;receivedAt=now();end(200,{accepted:true});return true;
  }
  if(!['GET','HEAD'].includes(request.method)){response.setHeader('Allow','GET, HEAD, POST');end(405,{code:'METHOD_NOT_ALLOWED'});return true;}
  if(!frame||now()-receivedAt>ttlMs){end(503,{code:'CAMERA_UNAVAILABLE'});return true;}
  response.writeHead(200,{'Content-Type':'image/jpeg','Content-Length':frame.length,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Received-At':new Date(receivedAt).toISOString()});
  response.end(request.method==='HEAD'?undefined:frame);return true;
 };
}
module.exports={createGuestCamera};
