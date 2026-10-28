// Runs in either exported repository, without Python packages or a DM host.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,readFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const profile=JSON.parse(readFileSync(path.join(root,'package.json'),'utf8')).name==='microscopy-core'?'core':'dm';
function client(environment={}) {
  const dir=mkdtempSync(path.join(tmpdir(),'split-boundary-'));
  const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('DM_')&&!key.startsWith('MICROSCOPY_')));
  Object.assign(env,{MICROSCOPY_IMAGE_WORKSPACE:path.join(dir,'images'),MICROSCOPY_PYTHON:'__must_not_start_python__',MICROSCOPY_PANEL:'0'},environment);
  const child=spawn(process.execPath,[path.join(root,'server.mjs')],{cwd:dir,env,stdio:['pipe','pipe','pipe']});
  let sequence=0,buffer='',stderr='';const pending=new Map();
  const rejectAll=error=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(error);}pending.clear();};
  const exited=new Promise(resolve=>{child.once('error',error=>{rejectAll(error);resolve({error});});child.once('exit',(code,signal)=>{rejectAll(new Error(`Child exited ${code}: ${stderr}`));resolve({code,signal});});});
  child.stdin.on('error',rejectAll);child.stderr.on('data',chunk=>{stderr=(stderr+chunk).slice(-8000);});
  child.stdout.on('data',chunk=>{buffer+=chunk;let end;while((end=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);try{const row=JSON.parse(line),p=pending.get(row.id);if(p){pending.delete(row.id);clearTimeout(p.timer);p.resolve(row);}}catch(error){rejectAll(error);}}});
  return {dir,rpc:(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(new Error(`RPC timeout: ${stderr}`));},10000);pending.set(id,{resolve,reject,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');}),async close(){child.stdin.end();const timer=setTimeout(()=>child.kill(),5000);try{const result=await exited;assert.equal(result.code,0,stderr);}finally{clearTimeout(timer);rejectAll(new Error('closed'));rmSync(dir,{recursive:true,force:true});}}};
}
test(`${profile}: independent catalog, namespace and no Python/DM startup`,async()=>{
  const c=client(profile==='core'?{DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:'deliberately-invalid'}:{DM_MCP_BACKEND:'python',MICROSCOPY_CONTEXT_WORKSPACE:'invalid-relative-path'});
  try {
    const init=await c.rpc('initialize');assert.equal(init.error,undefined);
    assert.equal(init.result.serverInfo.name,profile==='core'?'microscopy-core':'digitalmicrograph');
    const names=(await c.rpc('tools/list')).result.tools.map(t=>t.name);
    assert.ok(names.length>0);
    if(profile==='core'){assert.ok(names.includes('image_fft'));assert.ok(names.every(n=>!n.startsWith('dm_')));assert.equal(existsSync(path.join(root,'bridge')),false);assert.equal(existsSync(path.join(root,'lib/native_bridge.mjs')),false);}
    else {assert.ok(names.includes('dm_status'));assert.ok(names.every(n=>n.startsWith('dm_')));assert.equal(existsSync(path.join(root,'lib/image_workspace.mjs')),false);}
    const rejected=await c.rpc('tools/call',{name:profile==='core'?'dm_status':'image_open',arguments:{}});
    assert.ok(rejected.error||rejected.result?.isError===true);
    assert.equal(existsSync(path.join(c.dir,'images')),false,'catalog discovery must not start a science worker');
  }finally{await c.close();}
});
if(profile==='dm')test('DM native catalog keeps its own qualified namespaces without a science installation',async()=>{
  const c=client({DM_MCP_BACKEND:'native',DM_NATIVE_SESSION:'a'.repeat(32)});
  try {const names=(await c.rpc('tools/list')).result.tools.map(t=>t.name);assert.ok(names.includes('dm_native_result'));assert.ok(names.every(n=>n.startsWith('dm_')));}finally{await c.close();}
});
