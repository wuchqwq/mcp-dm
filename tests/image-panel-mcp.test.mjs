// Manager/stdio boundaries, not a browser or real DM qualification.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,readdirSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {ImagePanelManager,imagePanelTools} from '../lib/image_panel_mcp.mjs';

const A='a'.repeat(32),B='b'.repeat(32),C='c'.repeat(32);
const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==';
const unpack=result=>JSON.parse(result.content.find(part=>part.type==='text').text);
function fixture(){
  const workspace=mkdtempSync(path.join(tmpdir(),'dm-panel-tools-'));
  const calls=[],receipts=new Map(),connections=new Map();let launches=0,unknown=false,dropNext=false;
  const state={schema_version:1,object:{object_id:A,kind:'view'},png_base64:png,edit_state:{draft_revision:0,dirty:false,gesture_active:false,selection:null,base_object_id:A},selection:null};
  const options={workspace,python:path.resolve('external-python.exe'),inspect:async id=>{calls.push({inspect:id});if(unknown)throw new Error('Unknown image object');},
    launch:async({panel_id,connection_file,object_id})=>{
      launches++;const records=readdirSync(path.join(workspace,'panel-registry','requests'));assert.ok(records.length,'original ID is durable before launch');
      const original=JSON.parse(readFileSync(path.join(workspace,'panel-registry','requests',records.at(-1))));assert.equal(original.status,'submitted');
      state.panel_id=panel_id;state.object.object_id=object_id;
      const record={schema_version:1,panel_id,port:32122+launches,token:'e'.repeat(48),pid:12345};connections.set(record.port,record);writeFileSync(connection_file,JSON.stringify(record),{flag:'wx'});
    },
    fetchImpl:async(url,options)=>{
      calls.push({url,method:options.method,body:options.body});const parsed=new URL(url);
      const conn=connections.get(Number(parsed.port));assert.ok(conn);assert.equal(parsed.hostname,'127.0.0.1');assert.equal(options.headers['X-Panel-Token'],'e'.repeat(48));
      let value={...structuredClone(state),panel_id:conn.panel_id},status=200;
      if(parsed.pathname==='/api/present'&&options.method==='POST'){
        const body=JSON.parse(options.body),original=JSON.parse(readFileSync(path.join(workspace,'panel-registry','requests',body.request_id+'.json')));assert.equal(original.status,'submitted');
        if(body.expected_object_id!==state.object.object_id){value={error:'Stale current object'};status=409;}
        else{
          const queued=state.edit_state.dirty||state.edit_state.gesture_active||state.edit_state.draft_revision!==body.draft_revision;
          if(queued)state.pending_result={object_id:body.object_id,request_id:body.request_id};else state.object={object_id:body.object_id,kind:'view'};
          value={...structuredClone(state),panel_id:conn.panel_id,presentation:{request_id:body.request_id,object_id:body.object_id,status:queued?'queued':'shown'}};
          receipts.set(body.request_id,value);
          if(dropNext){dropNext=false;throw new Error('Connection lost after acceptance');}
        }
      }else if(parsed.pathname==='/api/present'){
        value=receipts.get(parsed.searchParams.get('request_id'));if(!value){value={error:'Original presentation not found'};status=404;}
      }
      return {ok:status===200,status,async text(){return JSON.stringify(value);}};
    }};
  return {workspace,state,calls,receipts,options,manager:()=>new ImagePanelManager(options),get launches(){return launches;},set unknown(value){unknown=value;},set dropNext(value){dropNext=value;},close(){rmSync(workspace,{recursive:true,force:true});}};
}

test('formal panel schemas expose no caller paths/URLs/scripts and refuse invalid IDs before side effects',async()=>{
  const f=fixture(),manager=f.manager();try{
    assert.deepEqual(imagePanelTools.map(tool=>tool.name),['image_panel_open','image_panel_current','image_panel_show']);
    for(const tool of imagePanelTools)assert.equal(tool.inputSchema.additionalProperties,false);
    for(const args of [{object_id:A},{object_id:A,request_id:'../../bad'},{object_id:A,request_id:'r',url:'http://elsewhere'},{object_id:'front',request_id:'r'}])assert.throws(()=>manager.call('image_panel_open',args));
    assert.throws(()=>manager.call('image_panel_show',{panel_id:A,object_id:B,expected_object_id:A,draft_revision:-1,request_id:'bad'}));
    assert.equal(f.calls.length,0);assert.equal(f.launches,0);
    f.unknown=true;await assert.rejects(manager.call('image_panel_open',{object_id:A,request_id:'missing'}),/Unknown image/);assert.equal(f.launches,0);assert.deepEqual(readdirSync(path.join(f.workspace,'panel-registry','requests')),[]);
  }finally{f.close();}
});

test('open survives a fresh MCP manager, retains one panel and returns saved image plus exact unsaved selection',async()=>{
  const f=fixture();try{
    const opened=unpack(await f.manager().call('image_panel_open',{object_id:A,request_id:'open'}));
    assert.equal(opened.request_id,'open');assert.match(opened.panel_url,/^http:\/\/127\.0\.0\.1:32123\/#e+/);assert.equal(f.launches,1);
    f.state.selection={kind:'rectangle',coordinate_space:'source_pixels',source_object_id:B,coordinates:[3,4,10,12]};
    f.state.edit_state={draft_revision:4,dirty:true,gesture_active:false,selection:f.state.selection,base_object_id:A};
    const current=await f.manager().call('image_panel_current');const data=unpack(current);
    assert.equal(data.panel_id,opened.panel_id);assert.deepEqual(data.view.selection,f.state.selection);assert.equal(data.view.edit_state.dirty,true);assert.match(data.image_semantics,/not baked/);assert.equal(current.content[1].type,'image');assert.equal(data.automatic_model_wake,false);
    const recovered=unpack(await f.manager().call('image_panel_open',{request_id:'open',object_id:A}));assert.equal(recovered.panel_id,opened.panel_id);assert.equal(f.launches,1);
    await assert.rejects(f.manager().call('image_panel_open',{object_id:B,request_id:'open'}),/conflicts/);assert.equal(f.launches,1);
  }finally{f.close();}
});

test('cancellation stops only waiting, and querying the same original open never launches another helper',async()=>{
  const f=fixture();let release,started;const begun=new Promise(resolve=>started=resolve),baseLaunch=f.options.launch;
  f.options.launch=async args=>{started();await new Promise(resolve=>release=resolve);await baseLaunch(args);};
  try{
    const manager=f.manager(),controller=new AbortController(),args={object_id:A,request_id:'cancel-open'},waiting=manager.call('image_panel_open',args,controller.signal);
    await begun;controller.abort();await assert.rejects(waiting,/Stopped waiting/);
    await assert.rejects(f.manager().call('image_panel_open',args),/still unverified/);assert.equal(f.launches,0);
    release();const finished=unpack(await manager.call('image_panel_open',args));assert.equal(f.launches,1);
    const fresh=unpack(await f.manager().call('image_panel_open',args));assert.equal(fresh.panel_id,finished.panel_id);assert.equal(f.launches,1);
  }finally{release?.();f.close();}
});

test('result presentation preserves dirty drafts, binds original ID/parameters and recovers without another POST',async()=>{
  const f=fixture();try{
    const manager=f.manager(),opened=unpack(await manager.call('image_panel_open',{object_id:A,request_id:'open'}));
    f.state.edit_state={draft_revision:7,dirty:true,gesture_active:false,selection:{kind:'point',coordinates:[1,2]},base_object_id:A};
    const args={panel_id:opened.panel_id,object_id:B,expected_object_id:A,draft_revision:7,request_id:'show'};
    const shown=unpack(await manager.call('image_panel_show',args));assert.equal(shown.view.object.object_id,A);assert.equal(shown.view.presentation.status,'queued');assert.equal(shown.view.pending_result.object_id,B);assert.equal(shown.view.edit_state.dirty,true);
    assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
    const recovered=unpack(await f.manager().call('image_panel_show',args));assert.equal(recovered.view.presentation.status,'queued');assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
    await assert.rejects(manager.call('image_panel_show',{...args,object_id:C}),/conflicts/);assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
    const stale={...args,expected_object_id:C,request_id:'stale'};await assert.rejects(manager.call('image_panel_show',stale),/Stale current/);
    await assert.rejects(f.manager().call('image_panel_show',stale),/Stale current/);assert.equal(f.calls.filter(call=>call.method==='POST').length,2);
  }finally{f.close();}
});

test('lost presentation reply is queried using original receipt, never automatically submitted again',async()=>{
  const f=fixture();try{
    const opened=unpack(await f.manager().call('image_panel_open',{object_id:A,request_id:'open'}));
    const args={panel_id:opened.panel_id,object_id:B,expected_object_id:A,draft_revision:0,request_id:'lost-show'};f.dropNext=true;
    await assert.rejects(f.manager().call('image_panel_show',args),/Connection lost/);assert.equal(f.state.object.object_id,B);
    const recovered=unpack(await f.manager().call('image_panel_show',args));assert.equal(recovered.view.presentation.status,'shown');assert.equal(recovered.view.object.object_id,B);
    assert.equal(f.calls.filter(call=>call.method==='POST').length,1);assert.equal(f.calls.filter(call=>call.url?.includes('/api/present?request_id=lost-show')).length,1);
    f.receipts.clear();const second=unpack(await f.manager().call('image_panel_show',args));assert.equal(second.view.object.object_id,B);assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
  }finally{f.close();}
});

test('omitted current panel is never picked by recency, and tampered connection URLs cannot escape loopback',async()=>{
  const f=fixture();try{
    const first=unpack(await f.manager().call('image_panel_open',{object_id:A,request_id:'one'}));
    await f.manager().call('image_panel_open',{object_id:B,request_id:'two'});
    await assert.rejects(f.manager().call('image_panel_current'),/exactly one live/);
    const file=path.join(f.workspace,'panel-registry','panels',first.panel_id+'.json'),record=JSON.parse(readFileSync(file));writeFileSync(file,JSON.stringify({...record,url:'https://outside.example/'}));
    const calls=f.calls.length;await assert.rejects(f.manager().call('image_panel_current',{panel_id:first.panel_id}),/Invalid owned panel connection/);assert.equal(f.calls.length,calls);
  }finally{f.close();}
});

test('wrong live panel identity or malformed PNG never becomes a successful shared-view response',async()=>{
  const f=fixture();try{
    const opened=unpack(await f.manager().call('image_panel_open',{object_id:A,request_id:'open'})),fetchBase=f.options.fetchImpl;
    f.options.fetchImpl=async(...args)=>{const reply=await fetchBase(...args),data=JSON.parse(await reply.text());return {...reply,async text(){return JSON.stringify({...data,panel_id:B});}};};
    await assert.rejects(f.manager().call('image_panel_current',{panel_id:opened.panel_id}),/identity/);
    f.options.fetchImpl=fetchBase;f.state.png_base64=Buffer.from('not a PNG').toString('base64');
    await assert.rejects(f.manager().call('image_panel_current',{panel_id:opened.panel_id}),/not PNG/);
  }finally{f.close();}
});

function stdioClient(workspace,python){
  const child=spawn(process.execPath,[fileURLToPath(new URL('../server.mjs',import.meta.url))],{env:{...process.env,DM_MCP_BACKEND:'images',DM_IMAGE_WORKSPACE:workspace,DM_IMAGE_PYTHON:python},windowsHide:true,stdio:['pipe','pipe','pipe']});
  let buffer='',number=0,stderr='';const waiting=new Map();child.stderr.on('data',chunk=>stderr+=chunk);child.stdin.on('error',()=>{});
  child.stdout.on('data',chunk=>{buffer+=chunk;let split;while((split=buffer.indexOf('\n'))>=0){const msg=JSON.parse(buffer.slice(0,split));buffer=buffer.slice(split+1);const pending=waiting.get(msg.id);if(pending){waiting.delete(msg.id);clearTimeout(pending.timer);pending.resolve(msg);}}});
  const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=++number,timer=setTimeout(()=>{waiting.delete(id);reject(new Error('Stdio panel timeout '+stderr));},60000);waiting.set(id,{resolve,timer});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
  return {rpc,async tool(name,args){const msg=await rpc('tools/call',{name,arguments:args});assert.equal(msg.error,undefined,JSON.stringify(msg.error));assert.notEqual(msg.result.isError,true,JSON.stringify(msg.result));return msg.result;},async close(){if(child.exitCode===null)await new Promise(resolve=>{child.once('exit',resolve);child.stdin.end();});}};
}

test('actual stdio MCP opens persistent owned panel, reads selection, queues dirty result and exports unchanged synthetic science',async()=>{
  const directory=mkdtempSync(path.join(tmpdir(),'dm-panel-stdio-')),workspace=path.join(directory,'workspace'),source=path.join(directory,'synthetic.tiff');let client,panelPid;
  try{
    const pythonCommand=process.env.DM_IMAGE_PYTHON||process.env.DM_TEST_PYTHON||'python';
    const executable=spawnSync(pythonCommand,['-c','import sys; print(sys.executable)'],{encoding:'utf8'});assert.equal(executable.status,0,executable.stderr);const python=executable.stdout.trim();
    const made=spawnSync(python,['-c','import numpy as np,tifffile,sys; a=np.arange(16*24,dtype=np.uint16).reshape(16,24);tifffile.imwrite(sys.argv[1],np.stack([a,a+10]),photometric="minisblack",metadata=None)',source],{encoding:'utf8'});assert.equal(made.status,0,made.stderr);
    const sourceBefore=readFileSync(source);client=stdioClient(workspace,python);
    const sourceObject=unpack(await client.tool('image_open',{source_path:source,request_id:'source'}));
    const frame=unpack(await client.tool('image_frame',{object_id:sourceObject.object_id,frame_index:0,request_id:'frame'}));
    const view=unpack(await client.tool('image_preview',{object_id:frame.object_id,max_size:64,request_id:'view'}));
    const openedMessage=await client.tool('image_panel_open',{object_id:view.object_id,request_id:'panel-open'}),opened=unpack(openedMessage);assert.ok(openedMessage.content.some(part=>part.type==='image'));
    const registry=JSON.parse(readFileSync(path.join(workspace,'panel-registry','panels',opened.panel_id+'.json')));panelPid=registry.pid;
    assert.equal(opened.view.panel_id,opened.panel_id);assert.equal(opened.view.object.object_id,view.object_id);
    await client.close();client=stdioClient(workspace,python);
    const recovered=unpack(await client.tool('image_panel_open',{object_id:view.object_id,request_id:'panel-open'}));assert.equal(recovered.panel_id,opened.panel_id);assert.equal(readdirSync(path.join(workspace,'panel-registry','panels')).length,1);
    const origin=opened.panel_url.split('/#')[0],headers={'X-Panel-Token':registry.token,Origin:origin,'Content-Type':'application/json'};
    const selected={kind:'rectangle',coordinate_space:'source_pixels',source_object_id:frame.object_id,coordinates:[3,4,15,12],panel:opened.view.object.panels[0]};
    const action=async(action,params,draft_revision=0)=>{const response=await fetch(origin+'/api/action',{method:'POST',headers,body:JSON.stringify({expected_object_id:view.object_id,draft_revision,action,params})});const state=await response.json();assert.equal(response.status,200,JSON.stringify(state));return state;};
    await action('select',{selection:selected});
    let current=unpack(await client.tool('image_panel_current',{}));assert.deepEqual(current.view.selection,selected);
    const fft=unpack(await client.tool('image_fft',{object_id:frame.object_id,rect:selected.coordinates,window:'none',subtract_mean:false,request_id:'fft'}));const fftBefore=readFileSync(fft.array_path);
    await action('draft',{draft_revision:1,dirty:true,gesture_active:false,selection:selected});
    const showArgs={panel_id:opened.panel_id,object_id:fft.object_id,expected_object_id:view.object_id,draft_revision:1,request_id:'panel-result'};
    const queued=unpack(await client.tool('image_panel_show',showArgs));assert.equal(queued.view.presentation.status,'queued');assert.equal(queued.view.object.object_id,view.object_id);assert.equal(queued.view.pending_result.object_id,fft.object_id);
    await action('draft',{draft_revision:2,dirty:false,gesture_active:false,selection:selected},1);await action('accept-result',{},2);
    current=unpack(await client.tool('image_panel_current',{}));assert.equal(current.view.object.object_id,fft.object_id);assert.equal(current.view.edit_state.dirty,false);
    const replay=unpack(await client.tool('image_panel_show',showArgs));assert.equal(replay.view.presentation.status,'queued');assert.equal(unpack(await client.tool('image_panel_current',{})).view.object.object_id,fft.object_id,'historical receipt must not reset current');
    const output=path.join(directory,'export');await client.tool('image_export',{object_id:fft.object_id,output_dir:output,request_id:'export'});
    assert.deepEqual(readFileSync(path.join(output,'data.npy')),fftBefore);assert.deepEqual(readFileSync(fft.array_path),fftBefore);assert.deepEqual(readFileSync(source),sourceBefore);
  }finally{
    await client?.close();
    // Only the helper launched in this isolated test is ended, never DM or a
    // pre-existing user panel. Its stdio MCP child exits on pipe EOF.
    if(panelPid){try{process.kill(panelPid,'SIGTERM');}catch(error){if(error.code!=='ESRCH')throw error;}await new Promise(resolve=>setTimeout(resolve,200));}
    rmSync(directory,{recursive:true,force:true});
  }
});
