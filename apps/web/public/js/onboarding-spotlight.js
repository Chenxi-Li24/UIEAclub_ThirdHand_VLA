/* Presentation geometry only. No robot commands or service access. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandOnboardingSpotlight=api;})(globalThis,function(){
 'use strict';
 const intersect=(a,b)=>{const x=Math.max(a.x,b.x),y=Math.max(a.y,b.y),right=Math.min(a.x+a.width,b.x+b.width),bottom=Math.min(a.y+a.height,b.y+b.height);return right>x&&bottom>y?{x,y,width:right-x,height:bottom-y}:null;};
 const area=(a,b)=>{const r=intersect(a,b);return r?r.width*r.height:0;};
 function dimRects(viewport,holes){
  const bounds={x:0,y:0,...viewport},clear=holes.map(r=>intersect(r,bounds)).filter(Boolean);
  const edges=[...new Set([0,viewport.width,...clear.flatMap(r=>[r.x,r.x+r.width])])].sort((a,b)=>a-b),result=[];
  for(let i=1;i<edges.length;i++){
   const x=edges[i-1],width=edges[i]-x,intervals=clear.filter(r=>r.x<x+width&&r.x+r.width>x).map(r=>[r.y,r.y+r.height]).sort((a,b)=>a[0]-b[0]);let y=0;
   for(const [top,bottom]of intervals){if(top>y)result.push({x,y,width,height:top-y});y=Math.max(y,bottom);}
   if(y<viewport.height)result.push({x,y,width,height:viewport.height-y});
  }
  return result;
 }
 function placePanel(viewport,size,target,exclusions=[]){
  const margin=12,gap=18,width=Math.min(size.width,viewport.width-2*margin),height=Math.min(size.height,viewport.height-2*margin);
  const clamp=(n,max)=>Math.max(margin,Math.min(n,max-margin));
  const candidates=target?[
   {x:target.x+target.width+gap,y:target.y,side:'left'},
   {x:target.x-width-gap,y:target.y,side:'right'},
   {x:target.x+(target.width-width)/2,y:target.y+target.height+gap,side:'top'},
   {x:target.x+(target.width-width)/2,y:target.y-height-gap,side:'bottom'},
  ]:[{x:(viewport.width-width)/2,y:(viewport.height-height)/2,side:'none'}];
  candidates.push({x:viewport.width-width-margin,y:viewport.height-height-margin,side:'none'},{x:margin,y:viewport.height-height-margin,side:'none'});
  const chosen=candidates.map((c,index)=>{const r={...c,x:clamp(c.x,viewport.width-width),y:clamp(c.y,viewport.height-height),width,height};return {...r,exclusionArea:exclusions.reduce((sum,h)=>sum+area(r,h),0),lessonArea:target?area(r,target):0,index};}).sort((a,b)=>a.exclusionArea-b.exclusionArea||a.lessonArea-b.lessonArea||a.index-b.index)[0];
  if(chosen.exclusionArea>0){const top=Math.max(margin,...exclusions.map(r=>r.y+r.height+margin));return {...chosen,y:top,height:Math.max(0,viewport.height-margin-top),side:'none'};}
  return chosen;
 }
 function mountSpotlight(doc,win,panel,{onTargetVisibilityChange=()=>{}}={}){
  const root=doc.createElement('div');root.id='onboarding-spotlight';root.hidden=true;
  const shades=doc.createElement('div'),outlines=doc.createElement('div');shades.className='onboarding-shades';outlines.className='onboarding-outlines';shades.setAttribute('aria-hidden','true');outlines.setAttribute('aria-hidden','true');
  root.append(shades,outlines,panel);doc.body.appendChild(root);panel.setAttribute('role','dialog');panel.setAttribute('aria-labelledby','onboarding-title');panel.setAttribute('aria-modal','false');
  let targets=[],active=false,visible=false,pending=false,available=true,requireTarget=false,watched=[];
  const viewport=()=>({width:win.innerWidth||doc.documentElement.clientWidth||1280,height:win.innerHeight||doc.documentElement.clientHeight||800});
  function rectFor(node,pad=0){
   if(!node||node.closest('[hidden]'))return null;
   const r=node.getBoundingClientRect?.();if(!r||r.width<=0||r.height<=0)return null;
   let rect={x:r.x-pad,y:r.y-pad,width:r.width+pad*2,height:r.height+pad*2};
   for(let parent=node.parentElement;parent&&rect;parent=parent.parentElement){
    const style=win.getComputedStyle?.(parent);if(style?.display==='none'||style?.visibility==='hidden')return null;
    if(/auto|scroll|hidden|clip/.test(`${style?.overflow} ${style?.overflowX} ${style?.overflowY}`)){
     const clip=parent.getBoundingClientRect?.();if(clip)rect=intersect(rect,{x:clip.x,y:clip.y,width:clip.width,height:clip.height});
    }
   }
   return rect&&intersect(rect,{x:0,y:0,...viewport()});
  }
  const applyRect=(node,r)=>{for(const key of ['x','y','width','height'])node.style[key==='x'?'left':key==='y'?'top':key]=`${r[key]}px`;};
  function refresh(){
   pending=false;root.hidden=!visible;if(!visible)return;
   const view=viewport(),stop=rectFor(doc.getElementById('btn-estop-top'),6),lesson=targets.map(node=>rectFor(node,6)).filter(Boolean);
   const primary=lesson[0]||null;available=(!requireTarget&&targets.length===0)||Boolean(primary);
   onTargetVisibilityChange(available);
   const dimmed=active&&available;root.dataset.dimmed=String(dimmed);shades.hidden=!dimmed;outlines.hidden=!dimmed;
   shades.replaceChildren();outlines.replaceChildren();
   if(dimmed){
    for(const r of dimRects(view,[...lesson,...(stop?[stop]:[])])){const shade=doc.createElement('div');shade.className='onboarding-shade';applyRect(shade,r);shades.appendChild(shade);}
    for(const r of lesson){const outline=doc.createElement('div');outline.className='onboarding-spotlight-outline';applyRect(outline,r);outlines.appendChild(outline);}
   }
   panel.style.width=`${Math.min(360,view.width-24)}px`;panel.style.maxHeight=`${view.height-24}px`;
   const size={width:Math.min(360,view.width-24),height:panel.offsetHeight||240};
   const position=placePanel(view,size,primary,stop?[stop]:[]);applyRect(panel,position);panel.style.height='';panel.style.maxHeight=`${position.height}px`;panel.dataset.side=position.side;
  }
  function schedule(){if(!pending){pending=true;win.requestAnimationFrame(refresh);}}
  const resize=win.ResizeObserver?new win.ResizeObserver(schedule):null;resize?.observe(panel);
  function update(nodes,settings){
   targets=nodes.filter(Boolean);active=settings.active;visible=settings.visible;requireTarget=settings.requireTarget===true;
   if(targets.length!==watched.length||targets.some((node,i)=>node!==watched[i])){for(const node of watched)resize?.unobserve(node);for(const node of targets)resize?.observe(node);watched=targets.slice();}
   refresh();
  }
  function hide(){visible=false;active=false;root.hidden=true;root.dataset.dimmed='false';shades.replaceChildren();outlines.replaceChildren();}
  doc.addEventListener('scroll',schedule,true);win.addEventListener('resize',schedule);
  doc.addEventListener('click',()=>{if(visible)schedule();},true);
  shades.addEventListener('wheel',event=>event.preventDefault(),{passive:false});
  const observer=new win.MutationObserver(()=>{if(visible)schedule();});observer.observe(doc.getElementById('workspace-pages'),{attributes:true,subtree:true,attributeFilter:['hidden','class']});
  doc.addEventListener('keydown',event=>{
   if(event.key!=='Tab'||!visible||!active||!available)return;
   const selector='button,input,select,textarea,a[href],[tabindex]';
   const nodes=[...panel.querySelectorAll(selector),...targets.flatMap(node=>[...(node.matches(selector)?[node]:[]),...node.querySelectorAll(selector)]),doc.getElementById('btn-estop-top')];
   const allowed=[...new Set(nodes)].filter(node=>node&&!node.disabled&&node.tabIndex!==-1&&rectFor(node));if(!allowed.length)return;
   const index=allowed.indexOf(doc.activeElement),next=index<0?0:(index+(event.shiftKey?-1:1)+allowed.length)%allowed.length;event.preventDefault();allowed[next].focus();
  },true);
  return {update,hide,refresh:schedule,get targetVisible(){return available;}};
 }
 return {dimRects,placePanel,mountSpotlight};
});
