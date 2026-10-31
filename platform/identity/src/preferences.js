'use strict';
const { transaction } = require('../../storage/src/pool');
const { identityError } = require('./errors');

function validatePreferences(value) {
  if (!value || !['en','zh-CN'].includes(value.locale) || !['light','dark'].includes(value.themeId) ||
    Object.keys(value).some(key=>!['locale','themeId','backgroundConfig','revision'].includes(key))) throw identityError('INVALID_INPUT');
  const background = value.backgroundConfig;
  if (!background || !['soft','plain'].includes(background.kind) || !/^#[a-f0-9]{6}$/i.test(background.color) ||
    Object.keys(background).some(key=>!['kind','color'].includes(key))) throw identityError('INVALID_INPUT');
  return {locale:value.locale,themeId:value.themeId,backgroundConfig:{kind:background.kind,color:background.color.toLowerCase()}};
}
function createPreferences({ pool }) {
  async function read(client,userId,lock=false) {
    if (!userId) throw identityError('UNAUTHENTICATED');
    const row=(await client.query(`SELECT u.locale,p.theme_id AS "themeId",p.background_config AS "backgroundConfig",p.revision
      FROM auth.user_preferences p JOIN auth.users u ON u.id=p.user_id WHERE p.user_id=$1${lock?' FOR UPDATE OF p,u':''}`,[userId])).rows[0];
    if (!row) throw identityError('NOT_FOUND');
    if (!Object.keys(row.backgroundConfig).length) row.backgroundConfig={kind:'soft',color:'#fffcf9'};
    return row;
  }
  async function write(client,userId,value) {
    const valid=validatePreferences(value);
    await client.query('UPDATE auth.users SET locale=$2,updated_at=now() WHERE id=$1',[userId,valid.locale]);
    const row=(await client.query('UPDATE auth.user_preferences SET theme_id=$2,background_config=$3,revision=revision+1,updated_at=now() WHERE user_id=$1 RETURNING revision',[userId,valid.themeId,valid.backgroundConfig])).rows[0];
    return {...valid,revision:row.revision};
  }
  return {
    async load({principal,guestSelection}) {
      return transaction(pool,async client=>{
        const stored=await read(client,principal?.userId,true);
        const changed=guestSelection?.changed || [];
        if (!Array.isArray(changed)||changed.some(key=>!['locale','themeId','backgroundConfig'].includes(key))) throw identityError('INVALID_INPUT');
        if (!changed.length) return stored;
        const next={...stored};for(const key of changed)next[key]=guestSelection.value?.[key];
        return write(client,principal.userId,next);
      });
    },
    async save({principal,value,expectedRevision}) {
      return transaction(pool,async client=>{
        const stored=await read(client,principal?.userId,true);
        if (!Number.isInteger(expectedRevision)||expectedRevision!==stored.revision) throw identityError('CONFLICT');
        return write(client,principal.userId,value);
      });
    }
  };
}
module.exports={createPreferences,validatePreferences};
