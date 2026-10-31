'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createTutorialAdapter,resolveEntry,scopedTutorialView}=require('../../../apps/web/public/js/tutorial-adapter');
test('an unbound tutorial never invents completion or an entry; a provider must return an approved local path',async()=>{
  const unavailable=createTutorialAdapter();
  assert.deepEqual(await unavailable.getState({userId:'user-a'}),{status:'unavailable'});
  assert.equal(unavailable.getEntry({locale:'en',theme:'light',returnTo:'/control'}),null);
  assert.equal((await unavailable.verifyCompletion({userId:'user-a',version:'v1'})).trusted,false);
  const adapter=createTutorialAdapter({allowedPrefixes:['/learn/'],provider:{getState:async()=>({status:'not_started',version:'v1'}),getEntry:()=>({path:'https://attacker.invalid/'}),verifyCompletion:async()=>({trusted:true,completed:true,version:'v1'})}});
  assert.equal(adapter.getEntry({locale:'en',theme:'light',returnTo:'/control'}),null);
  assert.equal(resolveEntry({tutorialState:{status:'unavailable'},entry:null,returnTo:'//attacker.invalid'}),'/control');
  assert.equal(resolveEntry({tutorialState:{status:'not_started'},entry:{path:'/learn/start'},returnTo:'/control'}),'/learn/start');
  assert.equal(resolveEntry({tutorialState:{status:'deferred'},entry:{path:'/learn/start'},returnTo:'/control'}),'/control');
});
test('tutorial browser progress is scoped to the account while all other workspace storage remains shared normally',()=>{
  const values=new Map(),view={localStorage:{getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value)},requestAnimationFrame(){},MutationObserver:class{},innerWidth:1280,innerHeight:800,addEventListener(){}};
  const a=scopedTutorialView(view,'user-a'),b=scopedTutorialView(view,'user-b');
  a.localStorage.setItem('thirdhand.onboarding.v1','completed');assert.equal(b.localStorage.getItem('thirdhand.onboarding.v1'),null);
  a.localStorage.setItem('thirdhand.nav-state','expanded');assert.equal(b.localStorage.getItem('thirdhand.nav-state'),'expanded');
  assert.equal(a.innerWidth,1280);
});
