'use strict';
async function loadWorkspaceBootstrap(pool,principal){
  // One non-locking read. Only the signed-in user's presentation data is sent.
  const row=(await pool.query(`SELECT u.display_name AS "displayName",u.locale,p.theme_id AS "themeId",
    p.layout_id AS "layoutId",p.classic_theme_id AS "classicThemeId",p.background_config AS "backgroundConfig",p.revision
    FROM auth.users u JOIN auth.user_preferences p ON p.user_id=u.id WHERE u.id=$1`,[principal.userId])).rows[0];
  if(!row)throw Error('Workspace preferences unavailable');
  const identity=Object.fromEntries(['userId','sessionId','role','mode','roleVersion','csrfToken'].map(key=>[key,principal[key]]));
  return {identity:{...identity,displayName:row.displayName},preferences:{locale:row.locale,
    themeId:row.themeId==='dark'?'dark':'light',classicThemeId:row.classicThemeId,layoutId:row.layoutId==='classic'?'classic':'workspace',
    backgroundConfig:['soft','plain'].includes(row.backgroundConfig?.kind)?row.backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:row.revision}};
}
module.exports={loadWorkspaceBootstrap};
