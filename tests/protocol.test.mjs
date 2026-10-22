import test from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {fileURLToPath} from 'node:url';

test('stdio validation, UTF-8 framing, serialized first connection, timeout and cancellation', async () => {
  const sockets = new Set();
  let connections = 0;
  const fake = net.createServer(socket => {
    connections++; sockets.add(socket); socket.on('close',()=>sockets.delete(socket)); socket.on('error',()=>{});
    socket.setEncoding('utf8'); socket.setNoDelay(true); let input = '';
    socket.on('data', chunk => {
      input += chunk; let i;
      while ((i=input.indexOf('\n'))>=0) {
        const req=JSON.parse(input.slice(0,i)); input=input.slice(i+1);
        const output=Buffer.from(JSON.stringify({id:req.id,ok:true,result:{backend:'test-only',name:'测试',op:req.op}})+'\n');
        const split=output.indexOf(Buffer.from('测'))+1;
        const send=()=> { if (!socket.destroyed) { socket.write(output.subarray(0,split)); setTimeout(()=>{if(!socket.destroyed)socket.write(output.subarray(split));},5); } };
        setTimeout(send,req.op==='stats'?750:0);
      }
    });
  });
  await new Promise((resolve,reject)=>{fake.once('error',reject);fake.listen(0,'127.0.0.1',resolve);});
  const child=spawn(process.execPath,[fileURLToPath(new URL('../server.mjs',import.meta.url))],{
    env:{...process.env,DM_BRIDGE_PORT:String(fake.address().port),DM_MCP_TIMEOUT_MS:'500'},stdio:['pipe','pipe','pipe']
  });
  let buffer='',next=1,stderr='';const pending=new Map(),messages=[];
  child.stderr.on('data',c=>stderr+=c);
  child.stdout.setEncoding('utf8');child.stdout.on('data',c=>{
    buffer+=c;let i;while((i=buffer.indexOf('\n'))>=0){const m=JSON.parse(buffer.slice(0,i));buffer=buffer.slice(i+1);messages.push(m);const w=pending.get(m.id);if(w){pending.delete(m.id);w(m);}}
  });
  const rpc=(method,params,id=next++)=>new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('MCP test timeout '+method+' '+stderr));},3000);
    pending.set(id,m=>{clearTimeout(timer);resolve(m);});child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');
  });
  try {
    assert.equal((await rpc('initialize',{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'regression',version:'1'}})).result.serverInfo.version,'0.6.0');
    child.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');
    const replies=await Promise.all(Array.from({length:8},()=>rpc('tools/call',{name:'dm_status',arguments:{}})));
    assert.equal(connections,1,'first concurrent requests must share one bridge connection');
    assert.ok(replies.every(m=>JSON.parse(m.result.content[0].text).name==='测试'),'split UTF-8 must round trip exactly');
    for(const params of [
      {name:'unknown',arguments:{}}, {name:'dm_stats',arguments:null},
      {name:'dm_stats',arguments:{extra:true}}, {name:'dm_profile',arguments:{x0:0,y0:0,x1:1,y1:1,width:256}},
      {name:'dm_crop',arguments:{rect:[2,0,1,3]}}, {name:'dm_open',arguments:{path:'relative.dm4'}}
    ]) assert.equal((await rpc('tools/call',params)).error.code,-32602);
    const parse = new Promise(resolve=>pending.set(null,resolve));child.stdin.write('{invalid json}\n');assert.equal((await parse).error.code,-32700);
    child.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/anything'})+'\n');
    await rpc('ping',{});
    assert.ok(!messages.some(m=>!Object.hasOwn(m,'id')),'no responses to notifications');
    const slow=await rpc('tools/call',{name:'dm_stats',arguments:{}});
    assert.equal(slow.result.isError,true);assert.match(slow.result.content[0].text,/状态未知/);
    await new Promise(r=>setTimeout(r,300));
    child.stdin.write(JSON.stringify({jsonrpc:'2.0',id:900,method:'tools/call',params:{name:'dm_stats',arguments:{}}})+'\n');
    await new Promise(r=>setTimeout(r,20));
    child.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/cancelled',params:{requestId:900}})+'\n');
    await new Promise(r=>setTimeout(r,800));
    assert.ok(!messages.some(m=>m.id===900),'cancelled request response must be suppressed');
    assert.ok((await rpc('tools/call',{name:'dm_status',arguments:{}})).result);
    const current=[...sockets][0];current.destroy();await new Promise(r=>setTimeout(r,30));
    assert.equal(JSON.parse((await rpc('tools/call',{name:'dm_status',arguments:{}})).result.content[0].text).name,'测试');
    assert.equal(connections,2,'reconnect after close');
  } finally {
    child.kill();await once(child,'exit');for(const s of sockets)s.destroy();await new Promise(r=>fake.close(r));
  }
});
