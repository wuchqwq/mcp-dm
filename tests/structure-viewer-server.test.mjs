// Actual stdio MCP + ASE worker + owned helper lifecycle. The pinned asset is
// a transport double, so these checks do not claim WebGL/browser acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {STRUCTURE_VIEWER_VERSION} from '../tools/structure_viewer.mjs';

const root=fileURLToPath(new URL('../',import.meta.url)),python=process.env.DM_STRUCTURE_PYTHON||process.env.DM_TEST_PYTHON||'python';
const optional={skip:!process.env.DM_STRUCTURE_PYTHON&&'Set DM_STRUCTURE_PYTHON to the independent ASE environment'};
const unpack=reply=>JSON.parse(reply.content.find(c=>c.type==='text').text);
function client(workspace,asset){
 const child=spawn(process.execPath,[path.join(root,'server.mjs')],{windowsHide:true,env:{...process.env,DM_MCP_BACKEND:'images',DM_IMAGE_WORKSPACE:path.join(workspace,'images'),DM_STRUCTURE_WORKSPACE:path.join(workspace,'structures'),DM_STRUCTURE_PYTHON:python,DM_IMAGE_PYTHON:python,DM_STRUCTURE_VIEWER_ASSET:asset},stdio:['pipe','pipe','pipe']});
 let next=1,buffer='',stderr='';const pending=new Map();child.stderr.on('data',c=>stderr+=c);child.stdin.on('error',()=>{});
 child.stdout.on('data',c=>{buffer+=c;let n;while((n=buffer.indexOf('\n'))>=0){const row=JSON.parse(buffer.slice(0,n));buffer=buffer.slice(n+1);const wait=pending.get(row.id);if(wait){pending.delete(row.id);clearTimeout(wait.timer);wait.resolve(row);}}});
 const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=next++,timer=setTimeout(()=>{pending.delete(id);reject(Error('MCP deadline '+stderr));},90000);pending.set(id,{resolve,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
 return {rpc,raw:(name,args)=>rpc('tools/call',{name,arguments:args}),async tool(name,args){const row=await rpc('tools/call',{name,arguments:args});assert.equal(row.error,undefined,JSON.stringify(row));assert.notEqual(row.result.isError,true,JSON.stringify(row));return row.result;},async close(){if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.stdin.end();});}};
}
test('MCP partial-cell views reuse a helper, original close recovers in a fresh client, and only a new view starts after confirmed shutdown',optional,async()=>{
 const directory=mkdtempSync(path.join(tmpdir(),'dm-viewer-mcp-')),workspace=path.join(directory,'workspace'),asset=path.join(directory,'node_modules','3dmol','build','3Dmol-min.js'),source=path.join(directory,'partial.xyz');
 mkdirSync(path.dirname(asset),{recursive:true});writeFileSync(asset,'/* transport double, not actual WebGL */');writeFileSync(path.join(path.dirname(path.dirname(asset)),'package.json'),JSON.stringify({name:'3dmol',version:STRUCTURE_VIEWER_VERSION,license:'BSD-3-Clause'}));writeFileSync(path.join(path.dirname(path.dirname(asset)),'LICENSE'),'BSD-3-Clause fixture');
 writeFileSync(source,'2\nLattice="3 0 0 -1 2 0 0 0 0" Properties=species:S:1:pos:R:3 pbc="T T F"\nC 0 0 0\nC 1 1 0\n');
 let c=client(workspace,asset);const owned=new Set();try{
  const catalog=(await c.rpc('tools/list')).result.tools;assert.ok(catalog.find(t=>t.name==='structure_viewer_close'));
  assert.equal((await c.raw('structure_viewer_close',{object_id:'a'.repeat(32)})).error.code,-32602);assert.equal(existsSync(path.join(workspace,'structures')),false);
  const bytes=readFileSync(source),opened=unpack(await c.tool('structure_open',{source_path:source,request_id:'partial-source'}));assert.equal(opened.cell_rank,2);
  const shown=await c.tool('structure_view',{object_id:opened.object_id,interactive:true,max_size:128,request_id:'partial-view-a'}),a=unpack(shown);owned.add(a.viewer_process_id);assert.equal(a.interactive_3d,'AVAILABLE_NOT_OBSERVED');assert.ok(shown.content.find(x=>x.type==='image'));
  const b=unpack(await c.tool('structure_view',{object_id:opened.object_id,interactive:true,max_size:128,request_id:'partial-view-b'}));owned.add(b.viewer_process_id);assert.notEqual(a.object_id,b.object_id);assert.equal(a.viewer_process_id,b.viewer_process_id);assert.equal(a.viewer_url,b.viewer_url);assert.equal(b.viewer_reused,true);
  const origin=a.viewer_url.split('/#')[0],snapshot=await(await fetch(origin+'/api/structure',{headers:{'X-Viewer-Token':a.viewer_url.split('#')[1]}})).json();assert.equal(snapshot.structure.cell_drawn,false);assert.deepEqual(snapshot.structure.periodic_cell_axes,[0,1]);assert.deepEqual(snapshot.structure.cell_angstrom[2],[0,0,0]);
  const args={object_id:b.object_id,request_id:'close-partial-helper'},closed=unpack(await c.tool('structure_viewer_close',args));assert.equal(closed.state,'completed');assert.equal(closed.viewer_process_stopped,true);assert.equal(closed.viewer_port_stopped,true);assert.deepEqual(closed.affected_view_object_ids,[a.object_id,b.object_id].sort());
  await c.close();c=client(workspace,asset);const recovered=unpack(await c.tool('structure_viewer_close',args));assert.equal(recovered.historical,true);assert.equal(recovered.viewer_owner_view_object_id,a.viewer_owner_view_object_id);
  const old=unpack(await c.tool('structure_view',{object_id:opened.object_id,interactive:true,max_size:128,request_id:'partial-view-a'}));assert.equal(old.object_id,a.object_id);assert.equal(old.interactive_3d,'UNVERIFIED');assert.equal(old.viewer_url,null);
  const fresh=unpack(await c.tool('structure_view',{object_id:opened.object_id,interactive:true,max_size:128,request_id:'partial-view-new'}));owned.add(fresh.viewer_process_id);assert.equal(fresh.interactive_3d,'AVAILABLE_NOT_OBSERVED');assert.notEqual(fresh.viewer_process_id,a.viewer_process_id);
  assert.equal(unpack(await c.tool('structure_viewer_close',{object_id:fresh.object_id,request_id:'close-new-helper'})).viewer_state,'closed');assert.deepEqual(readFileSync(source),bytes);
 }finally{await c.close();for(const pid of owned){if(!Number.isSafeInteger(pid))continue;try{process.kill(pid,'SIGTERM');}catch(error){if(error.code!=='ESRCH')throw error;}}await new Promise(resolve=>setTimeout(resolve,100));rmSync(directory,{recursive:true,force:true});}
});
