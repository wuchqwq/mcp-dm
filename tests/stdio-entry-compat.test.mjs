// Entry/facade compatibility only: no scientific Python, DM, browser or network.
import test from 'node:test';
import assert from 'node:assert/strict';
import {PassThrough} from 'node:stream';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {startMcpServer} from '../server.mjs';
import {startScienceServer} from '../science-server.mjs';
import {createServerRuntime} from '../lib/tools/create_server_runtime.mjs';
import {RpcError} from '../lib/runtime/schema.mjs';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(start,runtime){
  const input=new PassThrough(),output=new PassThrough(),messages=[],exits=[];
  let buffer='';
  output.setEncoding('utf8');
  output.on('data',chunk=>{
    buffer+=chunk;let end;
    while((end=buffer.indexOf('\n'))>=0){
      messages.push(JSON.parse(buffer.slice(0,end)));buffer=buffer.slice(end+1);
    }
  });
  const facade=start({runtime,input,output,exit:code=>exits.push(code)});
  return {messages,exits,close:()=>facade.close(),end:()=>input.end(),
    async send(message){input.write(typeof message==='string'?message+'\n':JSON.stringify(message)+'\n');await tick();return messages.at(-1);}};
}

for(const backend of ['python','native','images']){
  for(const image of [false,true])for(const structure of [false,true]){
    test(`legacy facade retains current catalog/identity: ${backend}, image=${image}, structure=${structure}`,async()=>{
      const dir=mkdtempSync(path.join(tmpdir(),'stdio-entry-'));
      const env={DM_MCP_BACKEND:backend,DM_NATIVE_SESSION:'a'.repeat(32),
        DM_IMAGE_PYTHON:path.join(dir,'unavailable-python'),DM_STRUCTURE_PYTHON:path.join(dir,'unavailable-python')};
      if(image||backend==='images')env.DM_IMAGE_WORKSPACE=path.join(dir,'images');
      if(structure)env.DM_STRUCTURE_WORKSPACE=path.join(dir,'structures');
      let client;
      try{
        const runtime=createServerRuntime({env}),expected=runtime.registry.listTools();
        client=harness(startMcpServer,runtime);
        const initialized=await client.send({jsonrpc:'2.0',id:1,method:'initialize',params:{}});
        assert.deepEqual(initialized.result.serverInfo,{name:'digitalmicrograph',version:'0.6.0'});
        assert.equal(initialized.result.protocolVersion,'2024-11-05');
        assert.deepEqual(initialized.result.capabilities,{tools:{listChanged:false}});
        assert.equal(initialized.result.instructions,runtime.instructions);
        const catalog=await client.send({jsonrpc:'2.0',id:2,method:'tools/list'});
        assert.deepEqual(catalog.result.tools,expected,'facade must not mutate names/order/schemas');
        if(backend==='images')assert.ok(expected.every(tool=>!tool.name.startsWith('dm_')));
        const ping=await client.send({jsonrpc:'2.0',id:3,method:'ping'});
        assert.deepEqual(ping.result,{});
        const missing=await client.send({jsonrpc:'2.0',id:4,method:'tools/call',params:{name:'not_a_tool',arguments:{}}});
        assert.equal(missing.error.code,-32602);
        client.end();await tick();client.close();assert.deepEqual(client.exits,[0]);
      }finally{client?.close();rmSync(dir,{recursive:true,force:true});}
    });
  }
}

for(const [name,start] of [['digitalmicrograph',startMcpServer],['microscopy-core',startScienceServer]]){
  test(`${name}: parse/errors/cancellation and close survive facade extraction`,async()=>{
    let closed=0,aborted=false,release;
    const runtime={instructions:'injected protocol fixture',registry:{listTools:()=>[],
      call(tool,args,{signal}){
        if(tool==='bad-args')throw new RpcError(-32602,'fixture argument error');
        if(tool==='failed')throw new Error('fixture worker error');
        if(tool==='wait')return new Promise(resolve=>{release=resolve;signal.addEventListener('abort',()=>{aborted=true;},{once:true});});
        return {content:[{type:'text',text:'fixture only'}]};
      }},close(){closed++;}};
    const client=harness(start,runtime);
    try{
      assert.equal((await client.send('{')).error.code,-32700);
      assert.equal((await client.send({jsonrpc:'1.0',id:1,method:'ping'})).error.code,-32600);
      assert.equal((await client.send({jsonrpc:'2.0',id:2,method:'unknown'})).error.code,-32601);
      const init=await client.send({jsonrpc:'2.0',id:3,method:'initialize'});
      assert.equal(init.result.serverInfo.name,name);
      const bad=await client.send({jsonrpc:'2.0',id:4,method:'tools/call',params:{name:'bad-args'}});
      assert.equal(bad.error.code,-32602);
      const failed=await client.send({jsonrpc:'2.0',id:5,method:'tools/call',params:{name:'failed'}});
      assert.equal(failed.result.isError,true);
      await client.send({jsonrpc:'2.0',id:6,method:'tools/call',params:{name:'wait'}});
      assert.equal(typeof release,'function');
      await client.send({jsonrpc:'2.0',method:'notifications/cancelled',params:{requestId:6}});
      assert.equal(aborted,true);
      release({content:[]});await tick();assert.ok(!client.messages.some(message=>message.id===6));
      client.end();await tick();client.close();assert.equal(closed,1);assert.deepEqual(client.exits,[0]);
    }finally{release?.({content:[]});client.close();}
  });
}
