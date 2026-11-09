'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const argon2=require('argon2');
const {validatePassword,hashPassword,verifyPassword}=require('../../../platform/identity/src/passwords');

test('new passwords require eight characters and both ASCII letter cases, with optional digits and symbols',()=>{
  for(const password of ['Abcdefgh','Abcdef12','Aa12345!','Aa'+'😀'.repeat(126)])assert.doesNotThrow(()=>validatePassword(password));
  for(const password of ['Abcdefg','abcdefgh','ABCDEFGH','12345678','!@#$%^&*','中文中文中文中文','Aa'+'😀'.repeat(127),null,12345678]){
    assert.throws(()=>validatePassword(password),{code:'INVALID_PASSWORD'});
  }
});

test('hashing enforces the new policy while existing passwords remain verifiable',async()=>{
  await assert.rejects(hashPassword('abcdefgh'),{code:'INVALID_PASSWORD'});
  const created=await hashPassword('Abcdefgh');
  assert.equal(await verifyPassword(created,'Abcdefgh'),true);
  assert.equal(await verifyPassword(created,'abcdefgh'),false);
  const legacy=await argon2.hash('legacy lowercase password',{type:argon2.argon2id,memoryCost:19456,timeCost:2,parallelism:1});
  assert.equal(await verifyPassword(legacy,'legacy lowercase password'),true);
});
