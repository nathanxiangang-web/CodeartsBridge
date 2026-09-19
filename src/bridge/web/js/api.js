const API='/api';
async function api(path,opts){const r=await fetch(API+path+'?_t='+Date.now(),{...opts,cache:'no-store'});try{return await r.json()}catch(e){return{error:String(e)}}}
