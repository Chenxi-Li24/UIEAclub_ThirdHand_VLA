'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const api=()=>require('../../../apps/web/public/js/onboarding-spotlight.js');
const covers=(r,x,y)=>x>=r.x&&x<r.x+r.width&&y>=r.y&&y<r.y+r.height;
const overlaps=(a,b)=>a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;
test('overlapping spotlight holes remain clear and all other viewport points are dimmed',()=>{
 const holes=[{x:20,y:20,width:40,height:40},{x:40,y:-10,width:40,height:50}];
 const shades=api().dimRects({width:100,height:100},holes);
 for(let x=1;x<100;x+=3)for(let y=1;y<100;y+=3){
  const clear=(x>=20&&x<60&&y>=20&&y<60)||(x>=40&&x<80&&y<40);
  assert.equal(shades.some(r=>covers(r,x,y)),!clear,`unexpected shade at ${x},${y}`);
 }
 assert.equal(shades.some(r=>covers(r,50,30)),false,'overlap cannot turn dark again');
 assert.ok(shades.every(r=>r.x>=0&&r.y>=0&&r.x+r.width<=100&&r.y+r.height<=100));
});
test('popup placement avoids the lesson and software stop when there is space',()=>{
 const target={x:800,y:200,width:120,height:60},stop={x:1120,y:15,width:140,height:40};
 const panel=api().placePanel({width:1280,height:800},{width:340,height:220},target,[stop]);
 assert.equal(overlaps(panel,target),false);assert.equal(overlaps(panel,stop),false);
 assert.ok(panel.x>=12&&panel.y>=12&&panel.x+panel.width<=1268&&panel.y+panel.height<=788);
});
test('narrow popup remains in view and below a model spotlight',()=>{
 const target={x:80,y:100,width:298,height:245},stop={x:275,y:6,width:103,height:36};
 const panel=api().placePanel({width:390,height:844},{width:360,height:240},target,[stop]);
 assert.equal(overlaps(panel,target),false);assert.equal(overlaps(panel,stop),false);
 assert.ok(panel.x>=12&&panel.x+panel.width<=378&&panel.y+panel.height<=832);
});
test('short viewport shrinks the dialog before it can cover software stop',()=>{
 const stop={x:275,y:6,width:103,height:36},target={x:80,y:70,width:298,height:120};
 const panel=api().placePanel({width:390,height:220},{width:360,height:300},target,[stop]);
 assert.equal(overlaps(panel,stop),false);assert.ok(panel.y+panel.height<=208);
});
