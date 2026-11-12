const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../../../apps/web/public');
test('all shipped HTML pages are English before JavaScript loads',()=>{
 for(const file of fs.readdirSync(root).filter(f=>f.endsWith('.html'))){
  const source=fs.readFileSync(path.join(root,file),'utf8');
  assert.doesNotMatch(source,/\p{Script=Han}/u,file);
  assert.doesNotMatch(source,/id="locale-zh"|value="zh-CN"/,file);
 }
});
test('legacy guest and account preferences cannot restore a non-English UI',async()=>{
 const {createPreferenceClient}=require('../../../apps/web/public/js/preferences');
 const view={localStorage:{getItem:()=>JSON.stringify({locale:'zh-CN'}),setItem(){}},addEventListener(){},removeEventListener(){}};
 const client=createPreferenceClient({view});
 assert.equal(client.current().locale,'en');
 await client.choose({locale:'zh-CN'});assert.equal(client.current().locale,'en');
 await client.hydrate({userId:'test'},{locale:'zh-CN'});assert.equal(client.current().locale,'en');
 client.dispose();
});
