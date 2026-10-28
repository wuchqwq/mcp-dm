import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createScienceRuntime} from '../lib/science/create_science_runtime.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const scopedDir=()=>mkdtempSync(path.join(tmpdir(),'microscopy-core-test-'));

test('standalone registry has science tools, optional providers and no DM tool entries',()=>{
  const dir=scopedDir();
  try{
    const runtime=createScienceRuntime({env:{
      MICROSCOPY_IMAGE_WORKSPACE:path.join(dir,'images'),
      MICROSCOPY_CONTEXT_WORKSPACE:path.join(dir,'contexts'),
      MICROSCOPY_STRUCTURE_WORKSPACE:path.join(dir,'structures'),
      MICROSCOPY_PYTHON:'/nonexistent/python',
      MICROSCOPY_PANEL:'1',
    }});
    const names=runtime.registry.listTools().map(tool=>tool.name);
    assert.ok(names.includes('image_open'));
    assert.ok(names.includes('image_panel_open'));
    assert.ok(names.includes('structure_open'));
    assert.ok(names.includes('analysis_create'));
    assert.ok(names.includes('image_fft'));
    assert.ok(names.every(name=>!name.startsWith('dm_')));
    assert.equal(runtime.backend,'science');
    assert.deepEqual(Object.keys(runtime.providers).sort(),['image','structure']);
    runtime.close();
  }finally{rmSync(dir,{recursive:true,force:true});}
});

test('invalid options cannot accidentally enable DM or use relative workspaces',()=>{
  assert.throws(()=>createScienceRuntime({env:{MICROSCOPY_IMAGE_WORKSPACE:'relative/images'}}),/absolute/);
  assert.throws(()=>createScienceRuntime({env:{MICROSCOPY_PANEL:'yes'}}),/0 or 1/);
  const dir=scopedDir();
  try{
    const runtime=createScienceRuntime({env:{MICROSCOPY_IMAGE_WORKSPACE:dir,MICROSCOPY_PANEL:'0'}});
    const names=runtime.registry.listTools().map(tool=>tool.name);
    assert.ok(names.includes('image_open'));
    assert.ok(!names.includes('image_panel_open'));
    assert.ok(!names.includes('structure_open'));
    runtime.close();
  }finally{rmSync(dir,{recursive:true,force:true});}
});

test('standalone stdio initializes without DM, rejects dm_status and validates image arguments',async()=>{
  const dir=scopedDir();
  const child=spawn(process.execPath,[path.join(root,'science-server.mjs')],{
    cwd:root,env:{
      ...process.env,
      MICROSCOPY_IMAGE_WORKSPACE:path.join(dir,'images'),
      MICROSCOPY_PYTHON:'/nonexistent/python',
      MICROSCOPY_PANEL:'0',
      MICROSCOPY_CONTEXT_WORKSPACE:'',
      MICROSCOPY_STRUCTURE_WORKSPACE:'',
    },stdio:['pipe','pipe','pipe']});
  let next=0,buffer='',stderr='';const pending=new Map();
  const exited=new Promise(resolve=>child.once('exit',code=>resolve(code)));
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stderr.on('data',chunk=>{stderr+=chunk;});
  child.stdout.on('data',chunk=>{
    buffer+=chunk;
    let end;
    while((end=buffer.indexOf('\n'))>=0){
      const row=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);
      const p=pending.get(row.id);if(p){clearTimeout(p.timer);pending.delete(row.id);p.resolve(row);}
    }
  });
  const rpc=(method,params)=>new Promise((resolve,reject)=>{
    const id=++next;
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('MCP timeout: '+stderr));},12000);
    pending.set(id,{resolve,reject,timer});
    child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');
  });
  try{
    const init=await rpc('initialize',{protocolVersion:'2024-11-05',capabilities:{}});
    assert.equal(init.error,undefined);
    assert.equal(init.result.serverInfo.name,'microscopy-core');
    const tools=(await rpc('tools/list',{})).result.tools.map(t=>t.name);
    assert.ok(tools.includes('image_open'));
    assert.ok(!tools.includes('dm_status'));
    assert.ok(!tools.includes('image_panel_open'));
    const rejected=await rpc('tools/call',{name:'dm_status',arguments:{}});
    assert.ok(rejected.error || rejected.result?.isError===true);
    const invalid=await rpc('tools/call',{name:'image_open',arguments:{source_path:'/synthetic/demo.tiff'}});
    assert.equal(invalid.error.code,-32602);
  }finally{
    child.stdin.end();
    assert.equal(await exited,0,stderr);
    for(const v of pending.values()){clearTimeout(v.timer);v.reject(new Error('child closed'));}
    rmSync(dir,{recursive:true,force:true});
  }
});
