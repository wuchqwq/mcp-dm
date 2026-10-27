import test from 'node:test';
import assert from 'node:assert/strict';
import {ExecutionCoordinator} from '../lib/runtime/execution_coordinator.mjs';
import {createExecutionModule} from '../lib/tools/execution_module.mjs';
import {createServerRuntime} from '../lib/tools/create_server_runtime.mjs';
import {ToolRegistry} from '../lib/runtime/tool_registry.mjs';
import path from 'node:path';
import os from 'node:os';

const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const image={provider:'external-image-workspace',workspace:'opaque-image-workspace',session:'workspace-journal-v1'};
const structure={provider:'external-structure-workspace',workspace:'opaque-structure-workspace',session:'workspace-journal-v1'};
function task(c,id,keys=[],scope=image,lane='work') {
  const output=defer(),closed=defer();let starts=0;
  const wait=c.invoke({operation:'synthetic-fixture',requestId:id,parameters:{id},resourceKeys:keys,requestScope:scope,lane,timeoutMs:1000},{start:()=>{starts++;return {result:output.promise,closed:closed.promise};}});wait.catch(()=>{});
  return {wait,output,closed,starts:()=>starts,finish:()=>{output.resolve('fixture');closed.resolve();}};
}

test('worker capacity is independent of resource conflicts and reserves a responsive query lane',async()=>{
  const c=new ExecutionCoordinator({capacity:{work:2,query:1}});
  const a=task(c,'same-id',['a']),b=task(c,'same-id',['b'],structure),pending=task(c,'third',['third']);
  assert.equal(pending.starts(),0);assert.equal(pending.wait.receipt().queueReason,'capacity');
  const query=task(c,'read',[],image,'query');assert.equal(query.starts(),1);
  a.output.resolve('done waiting');await a.wait;
  assert.equal(pending.starts(),0,'result does not free a still-live worker capacity slot');
  a.closed.resolve();await a.wait.workerDone;assert.equal(pending.starts(),1);
  assert.equal(c.list({requestScope:image,requestId:'same-id'}).length,1);
  assert.equal(c.list({requestScope:structure,requestId:'same-id'}).length,1);
  assert.throws(()=>c.inspect(a.wait.receipt().executionToken,{requestScope:structure}),/not found/);
  b.finish();pending.finish();query.finish();await c.whenIdle();
});

test('monotonic observations distinguish queue, actual start, wait cancellation and actual closure',async()=>{
  let tick=100;const c=new ExecutionCoordinator({clock:()=>tick,capacity:{work:1,query:1}});
  const a=task(c,'first',['same']);tick=110;
  const output=defer(),closed=defer(),controller=new AbortController();
  const wait=c.invoke({operation:'second',requestId:'second',parameters:{id:'second'},requestScope:image,resourceKeys:['same'],timeoutMs:1000},
    {start:()=>{tick=125;return {result:output.promise,closed:closed.promise};}},{signal:controller.signal});wait.catch(()=>{});
  tick=120;a.finish();await a.wait.workerDone;assert.equal(wait.receipt().timing.queueMs,10);
  assert.equal(wait.receipt().timing.startMs,5);tick=130;controller.abort();await assert.rejects(wait,/Stopped waiting/);
  tick=150;assert.equal(wait.receipt().closed,false);assert.equal(wait.receipt().timing.waitMs,20);
  output.resolve('late');closed.resolve();await wait.workerDone;
  const observed=c.inspect(wait.receipt().executionToken,{requestScope:image});
  assert.equal(observed.timing.closedAtMs,50);assert.equal(observed.timing.runMs,25);assert.equal(observed.waitState,'cancelled');
  assert.equal(observed.state,'completed');assert.equal(observed.requestRef.session,'workspace-journal-v1');
});

test('observations cross async registry dispatch and do not start workers or accept another scope',async()=>{
  const c=new ExecutionCoordinator(),running=task(c,'original',['science']);
  const module=createExecutionModule({coordinator:c,providers:{image,structure}}),registry=new ToolRegistry().register(module).seal();
  const list=JSON.parse((await registry.call('execution_list',{provider:'image',request_id:'original'})).content[0].text);
  assert.equal(list.observations[0].requestRef.requestId,'original');assert.equal(list.observations[0].state,'running');
  await assert.rejects(registry.call('execution_info',{provider:'structure',execution_id:list.observations[0].executionToken}),/not found/);
  assert.equal(running.starts(),1);running.finish();await c.whenIdle();
});

test('bounded terminal observation retention never evicts an active original request',async()=>{
  const c=new ExecutionCoordinator({maxObservations:2}),held=task(c,'held',['held']);
  for(let i=0;i<4;i++){const next=task(c,'done-'+i,['other']);next.finish();await next.wait.workerDone;}
  assert.equal(c.list({requestScope:image}).length,2);
  assert.equal(c.inspect(held.wait.receipt().executionToken,{requestScope:image}).closed,false);
  held.finish();await c.whenIdle();
});

test('normal provider composition shares one coordinator without requiring observation tools or Skills',()=>{
  const runtime=createServerRuntime({env:{DM_MCP_BACKEND:'images',DM_IMAGE_WORKSPACE:path.join(os.tmpdir(),'shared-budget-images'),DM_STRUCTURE_WORKSPACE:path.join(os.tmpdir(),'shared-budget-structures')}});
  assert.equal(runtime.providers.image.coordinator,runtime.coordinator);
  assert.equal(runtime.providers.structure.coordinator,runtime.coordinator);
  assert.equal(runtime.registry.listTools().some(d=>d.name==='execution_list'),false);runtime.close();
  const enabled=createServerRuntime({env:{DM_MCP_BACKEND:'images',DM_IMAGE_WORKSPACE:path.join(os.tmpdir(),'shared-budget-images'),DM_MCP_EXECUTION_OBSERVABILITY:'1'}});
  assert.ok(enabled.registry.listTools().some(d=>d.name==='execution_info'));enabled.close();
});
