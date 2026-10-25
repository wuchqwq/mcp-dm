// Actual Node MCP + independent Python worker; TIFF fixtures only, never DM.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,rmSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const python=process.env.DM_IMAGE_PYTHON||process.env.DM_TEST_PYTHON||'python';
function client(workspace,backend='images'){
 const child=spawn(process.execPath,[path.join(root,'server.mjs')],{env:{...process.env,DM_MCP_BACKEND:backend,DM_NATIVE_SESSION:'a'.repeat(32),DM_IMAGE_WORKSPACE:workspace,DM_IMAGE_PYTHON:python},stdio:['pipe','pipe','pipe']});
 let next=1,buffer='',stderr='';const pending=new Map();child.stderr.on('data',c=>stderr+=c);child.stdin.on('error',()=>{});
 child.stdout.on('data',c=>{buffer+=c;let n;while((n=buffer.indexOf('\n'))>=0){const msg=JSON.parse(buffer.slice(0,n));buffer=buffer.slice(n+1);const item=pending.get(msg.id);if(item){pending.delete(msg.id);clearTimeout(item.timer);item.resolve(msg);}}});
 const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=next++;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('MCP timeout '+stderr));},30000);pending.set(id,{resolve,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
 return {rpc,tool:(name,args={})=>rpc('tools/call',{name,arguments:args}),async close(){if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.stdin.end();});}};
}
function result(msg){assert.equal(msg.error,undefined);assert.notEqual(msg.result.isError,true,JSON.stringify(msg.result));return JSON.parse(msg.result.content[0].text);}
function picture(msg){const img=msg.result.content.find(c=>c.type==='image');assert.ok(img,'MCP returns image content, not only a path');assert.equal(img.mimeType,'image/png');assert.equal(Buffer.from(img.data,'base64').subarray(0,8).toString('hex'),'89504e470d0a1a0a');return img;}
function fixture(){const dir=mkdtempSync(path.join(tmpdir(),'dm-images-mcp-'));const source=path.join(dir,'source.tiff');
 const p=spawnSync(python,['-c',"import numpy as np,tifffile,sys; a=np.arange(16*24,dtype=np.uint16).reshape(16,24);tifffile.imwrite(sys.argv[1],np.stack([a,a+100,a+200]),photometric='minisblack',metadata=None)",source],{encoding:'utf8'});assert.equal(p.status,0,p.stderr);return {dir,source,workspace:path.join(dir,'workspace')};}

test('standalone image catalog needs no DM and native opt-in composes without fallback',async()=>{
 const f=fixture();const c=client(f.workspace);try{
  const init=await c.rpc('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'image-fixture',version:'1'}});assert.match(init.result.instructions,/independent Python/);
  const names=(await c.rpc('tools/list')).result.tools.map(t=>t.name);assert.equal(names.length,11);assert.ok(names.includes('image_fft'));assert.ok(!names.includes('dm_status'));
  assert.ok((await c.tool('dm_status')).error,'standalone mode refuses DM tools');
  const invalid=await c.tool('image_open',{source_path:f.source});assert.equal(invalid.error.code,-32602);assert.equal(existsSync(f.workspace),false);
 }finally{await c.close();}
 const native=client(f.workspace,'native');try{const names=(await native.rpc('tools/list')).result.tools.map(t=>t.name);assert.equal(names.length,31);assert.ok(names.includes('dm_native_frame'));assert.ok(names.includes('image_preview'));}finally{await native.close();rmSync(f.dir,{recursive:true,force:true});}
});

test('MCP TIFF frames, shared-range comparison, revised view, annotation and durable query compose',async()=>{
 const f=fixture();let c=client(f.workspace);try{
  const original=readFileSync(f.source);const opened=result(await c.tool('image_open',{source_path:f.source,request_id:'open'}));
  const a=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:0,request_id:'frame0'}));
  const b=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:2,request_id:'frame2'}));
  const compared=await c.tool('image_compare',{object_ids:[a.object_id,b.object_id],rect:[2,3,14,13],display_range:[0,600],gamma:1,request_id:'compare'});const before=result(compared);picture(compared);
  const revised=await c.tool('image_preview',{object_id:a.object_id,rect:[3,4,15,14],display_range:[50,400],gamma:0.8,request_id:'revised'});const v=result(revised);picture(revised);assert.notEqual(v.object_id,before.object_id);
  const annotated=await c.tool('image_annotate',{object_id:v.object_id,annotations:[{kind:'point',coordinates:[5,6],text:'candidate',status:'hypothesized'}],request_id:'mark'});const mark=result(annotated);picture(annotated);
  const retracted=await c.tool('image_annotate',{object_id:mark.object_id,annotations:[],request_id:'withdraw'});result(retracted);picture(retracted);
  const same=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:0,request_id:'frame0'}));assert.equal(same.object_id,a.object_id);
  const conflict=await c.tool('image_frame',{object_id:opened.object_id,frame_index:1,request_id:'frame0'});assert.equal(conflict.result.isError,true);
  await c.close();c=client(f.workspace);const recovered=result(await c.tool('image_result',{request_id:'compare'}));assert.equal(recovered.object_id,before.object_id);
  assert.deepEqual(readFileSync(f.source),original);
 }finally{await c.close();rmSync(f.dir,{recursive:true,force:true});}
});

test('pixel FFT/measurement/context/export retain inputs and reject invalid requests',async()=>{
 const f=fixture();const c=client(f.workspace);try{
  const opened=result(await c.tool('image_open',{source_path:f.source,request_id:'open'}));const a=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:1,request_id:'frame'}));
  const fft=await c.tool('image_fft',{object_id:a.object_id,rect:[2,3,14,13],window:'none',subtract_mean:true,request_id:'fft'});result(fft);picture(fft);
  const m=result(await c.tool('image_measure',{object_id:a.object_id,points:[[2,3],[5,7]],request_id:'measure'}));assert.equal(m.distance_pixels,5);
  const proposed=result(await c.tool('image_context',{object_id:a.object_id,metadata:{reconstruction_type:'ptychography',data_meaning:'unknown storage units',frame_meaning:'user-described slices',xy_scale:{x:0.1,y:0.2,unit:'nm',source:'synthetic user estimate, not measured'},source_text:'synthetic user context'},request_id:'context'}));
  const withdrawn=result(await c.tool('image_context',{object_id:proposed.object_id,metadata:{xy_scale:null,source_text:'user withdrew estimate'},request_id:'withdraw-context'}));assert.equal(withdrawn.user_context.xy_scale,null);
  const dest=path.join(f.dir,'new-export');result(await c.tool('image_export',{object_id:a.object_id,output_dir:dest,request_id:'export'}));
  assert.equal((await c.tool('image_export',{object_id:a.object_id,output_dir:dest,request_id:'overwrite'})).result.isError,true);
  assert.equal((await c.tool('image_preview',{object_id:a.object_id,rect:[0,0,25,16],request_id:'outside'})).result.isError,true);
  assert.equal((await c.tool('image_preview',{object_id:a.object_id,display_range:[2,1],request_id:'range'})).result.isError,true);
  assert.equal((await c.tool('image_frame',{object_id:opened.object_id,frame_index:99,request_id:'badframe'})).result.isError,true);
  assert.equal((await c.tool('image_frame',{object_id:opened.object_id,frame_index:0,request_id:'../../bad'})).error.code,-32602);
 }finally{await c.close();rmSync(f.dir,{recursive:true,force:true});}
});

test('multi-turn context and FFT presentation revisions stay usable through actual MCP',async()=>{
 const f=fixture();let c=client(f.workspace);try{
  const before=readFileSync(f.source);
  const opened=result(await c.tool('image_open',{source_path:f.source,request_id:'rev-open'}));
  const frame=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:1,request_id:'rev-frame'}));
  const context=result(await c.tool('image_context',{object_id:frame.object_id,metadata:{reconstruction_type:'ptychography',value_unit:null,source_text:'synthetic user context'},request_id:'rev-context'}));
  const view=result(await c.tool('image_preview',{object_id:context.object_id,display_range:[0,65535],gamma:1,max_size:64,request_id:'rev-view'}));
  const extra=result(await c.tool('image_context',{object_id:view.object_id,metadata:{frame_meaning:'slice index'},request_id:'rev-context-extra'}));
  assert.equal(extra.user_context.reconstruction_type,'ptychography');assert.equal(extra.user_context.value_unit,null);
  const gammaMessage=await c.tool('image_preview',{object_id:extra.object_id,gamma:2,request_id:'rev-gamma'});
  const gamma=result(gammaMessage);picture(gammaMessage);
  assert.deepEqual(gamma.display.display_range,[0,65535]);assert.equal(gamma.display.max_size,64);
  const reset=result(await c.tool('image_preview',{object_id:gamma.object_id,display_range:null,request_id:'rev-auto'}));
  assert.deepEqual(reset.display.display_range,[100,483]);assert.equal(reset.display.gamma,2);
  const fftMessage=await c.tool('image_fft',{object_id:extra.object_id,rect:[2,3,14,13],subtract_mean:true,request_id:'rev-fft'});
  const fft=result(fftMessage);picture(fftMessage);const raw=readFileSync(fft.array_path);
  const renderedMessage=await c.tool('image_preview',{object_id:fft.object_id,gamma:2,max_size:32,request_id:'rev-fft-render'});
  const rendered=result(renderedMessage);picture(renderedMessage);
  assert.equal(rendered.kind,'fft_view');assert.equal(rendered.fft_recomputed,false);
  assert.equal(rendered.spectrum_object_id,fft.object_id);assert.equal(rendered.user_context.frame_meaning,'slice index');
  assert.deepEqual(readFileSync(rendered.array_path),raw);assert.deepEqual(rendered.frequency_axes,fft.frequency_axes);
  const powerMessage=await c.tool('image_preview',{object_id:rendered.object_id,representation:'power',request_id:'rev-power'});
  const power=result(powerMessage);picture(powerMessage);assert.equal(power.display.representation,'power');assert.equal(power.display.gamma,2);
  const markedMessage=await c.tool('image_annotate',{object_id:power.object_id,annotations:[{kind:'point',coordinates:[6,5],status:'hypothesized'}],request_id:'rev-mark'});
  const marked=result(markedMessage);picture(markedMessage);
  assert.deepEqual(marked.annotations[0].source_mappings[0].frequency_cycles_per_pixel,[0,0]);
  assert.equal(marked.annotations[0].source_mappings[0].source_object_id,fft.object_id);
  const dest=path.join(f.dir,'revised-fft-export');result(await c.tool('image_export',{object_id:marked.object_id,output_dir:dest,request_id:'rev-export'}));
  assert.deepEqual(readFileSync(path.join(dest,'data.npy')),raw);
  assert.equal((await c.tool('image_preview',{object_id:frame.object_id,representation:'power',request_id:'rev-wrong-domain'})).result.isError,true);
  assert.equal((await c.tool('image_preview',{object_id:fft.object_id,representation:'phase',request_id:'rev-bad-mode'})).error.code,-32602);
  await c.close();c=client(f.workspace);
  const recoveredMessage=await c.tool('image_result',{request_id:'rev-fft-render'});picture(recoveredMessage);
  assert.equal(result(recoveredMessage).object_id,rendered.object_id);
  assert.deepEqual(readFileSync(f.source),before);assert.deepEqual(readFileSync(fft.array_path),raw);
 }finally{await c.close();rmSync(f.dir,{recursive:true,force:true});}
});
