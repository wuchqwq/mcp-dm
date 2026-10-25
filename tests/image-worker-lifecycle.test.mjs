// Real child processes with a standard-library fake worker only. This tests
// facade waiting/serialization and response refusal, not image science or DM.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {ImageWorkspace} from '../lib/image_workspace.mjs';

const python=process.env.DM_IMAGE_PYTHON||process.env.DM_TEST_PYTHON||'python';
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(predicate,label,timeoutMs=8000) {
  const deadline=Date.now()+timeoutMs;
  while(!predicate()) {
    if(Date.now()>=deadline)throw Error('Timed out waiting for '+label);
    await pause(15);
  }
}
function fixture(t,{timeoutMs=10000,spawnProcess}={}) {
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'dm-image-lifecycle-'));
  const workspace=path.join(directory,'workspace');fs.mkdirSync(workspace);
  const workerPath=path.join(directory,'fake_worker.py');
  fs.writeFileSync(workerPath,String.raw`import base64,json,pathlib,sys,time
r=json.load(sys.stdin);root=pathlib.Path(r['workspace']);root.mkdir(parents=True,exist_ok=True)
ident=r.get('request_id',r.get('query_request_id','readonly'));action=r['action'];case=r.get('test_case','complete')
record=root/('record-'+ident+'.json')
def emit(value,code=0):
 print(json.dumps(value),flush=True);sys.exit(code)
def incomplete():
 emit({'ok':False,'state':'unknown','request_id':ident,'automatic_retry':False,
       'error':{'code':'INCOMPLETE_REQUEST','message':'Original request remains incomplete; do not replay'}},1)
if action=='result':
 if not record.is_file():incomplete()
 saved=json.loads(record.read_text())
 if saved['state']!='completed':incomplete()
 emit({'ok':True,'result':saved['result']})
if action=='get':
 emit({'ok':True,'result':{'backend':'external-image-workspace','state':'completed','object_id':r.get('object_id')}})
(root/('started-'+ident)).write_text(action)
record.write_text(json.dumps({'state':'prepared'}))
if case=='hold':
 deadline=time.monotonic()+15
 while not (root/('release-'+ident)).is_file():
  if time.monotonic()>deadline:emit({'ok':False,'error':'fake worker hold expired'},9)
  time.sleep(.01)
result={'backend':'external-image-workspace','state':'completed','request_id':ident,'object_id':'object-'+ident}
if case in ('png','outside_png','large_png','non_png'):
 target=(root.parent if case=='outside_png' else root)/('preview-'+ident+'.png')
 png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==')
 if case=='large_png':png+=b'\0'*(2*1024*1024+1-len(png))
 if case=='non_png':png=b'This is not a scientific or display PNG'
 target.write_bytes(png);result['image_path']=str(target)
if case=='bad_backend':result['backend']='digitalmicrograph-native'
if case=='bad_state':result['state']='unknown'
if case=='pending':incomplete()
record.write_text(json.dumps({'state':'completed','result':result}))
(root/('finished-'+ident)).write_text('worker finished')
emit({'ok':True,'result':result},7 if case=='nonzero_success' else 0)
`);
  const instance=new ImageWorkspace({workspace,python,workerPath,timeoutMs,...(spawnProcess?{spawnProcess}:{})});
  const file=name=>path.join(workspace,name);
  t.after(async()=>{
    // End only this fixture's own children, even if an assertion failed.
    for(const name of fs.readdirSync(workspace)) if(name.startsWith('started-'))fs.writeFileSync(file('release-'+name.slice(8)),'release');
    await instance.queue.catch(()=>{});
    fs.rmSync(directory,{recursive:true,force:true});
  });
  return {instance,file,workspace,workerPath};
}
const call=(f,id,testCase,signal)=>f.instance.call('image_open',{source_path:'unused-fixture-source',request_id:id,test_case:testCase},signal);
const result=value=>JSON.parse(value.content[0].text);

test('cancellation ends waiting but a second write waits for actual worker closure; queries remain available',async t=>{
  const f=fixture(t),controller=new AbortController();
  const first=call(f,'cancel-a','hold',controller.signal);first.catch(()=>{});
  await until(()=>fs.existsSync(f.file('started-cancel-a')),'first worker start');
  controller.abort();await assert.rejects(first,/Stopped waiting.*may still finish/);
  const second=call(f,'write-b','complete');second.catch(()=>{});
  await pause(150);
  assert.equal(fs.existsSync(f.file('started-write-b')),false,'cancelled worker must still own the write slot');
  await assert.rejects(f.instance.call('image_result',{request_id:'cancel-a'}),/INCOMPLETE_REQUEST/);
  const info=await f.instance.call('image_info',{object_id:'existing-fixture-object'});
  assert.equal(result(info).object_id,'existing-fixture-object');
  assert.equal(fs.existsSync(f.file('started-write-b')),false,'read-only queries cannot free the write slot');
  fs.writeFileSync(f.file('release-cancel-a'),'release');
  assert.equal(result(await second).request_id,'write-b');
  await f.instance.queue;
  const recovered=result(await f.instance.call('image_result',{request_id:'cancel-a'}));
  assert.equal(recovered.request_id,'cancel-a');assert.equal(recovered.object_id,'object-cancel-a');
  assert.equal(recovered.backend,'external-image-workspace');
});

test('timeout is an unknown write outcome and a query never restarts the original request',async t=>{
  const f=fixture(t,{timeoutMs:3000});
  const pending=call(f,'deadline-a','hold');pending.catch(()=>{});
  await until(()=>fs.existsSync(f.file('started-deadline-a')),'deadline worker start');
  await assert.rejects(pending,/time limit.*incomplete.*original request_id/);
  await f.instance.queue;
  const stored=JSON.parse(fs.readFileSync(f.file('record-deadline-a.json'),'utf8'));
  assert.equal(stored.state,'prepared');
  await assert.rejects(f.instance.call('image_result',{request_id:'deadline-a'}),/INCOMPLETE_REQUEST/);
  assert.equal(fs.existsSync(f.file('finished-deadline-a')),false);
  assert.equal(result(await call(f,'after-deadline','complete')).request_id,'after-deadline');
  assert.equal(JSON.parse(fs.readFileSync(f.file('record-deadline-a.json'),'utf8')).state,'prepared');
});

test('a failed termination request is not a worker exit or permission to start the next write',async t=>{
  let killAttempts=0,writeStarts=0;
  const spawnProcess=(...args)=>{
    const child=spawn(...args);
    // Only this fixture's real child ignores termination. The error is a
    // controlled injection, not a claim of an actual operating-system EPERM.
    child.kill=()=>{killAttempts++;queueMicrotask(()=>child.emit('error',Object.assign(new Error('synthetic termination denied'),{code:'EPERM'})));return false;};
    return child;
  };
  const f=fixture(t,{timeoutMs:3000,spawnProcess});
  const actualRun=f.instance.run.bind(f.instance);
  f.instance.run=(payload,signal)=>{if(!['result','get'].includes(payload.action))writeStarts++;return actualRun(payload,signal);};
  const first=call(f,'kill-denied','hold');first.catch(()=>{});
  await until(()=>fs.existsSync(f.file('started-kill-denied')),'controlled termination worker start');
  await assert.rejects(first,/time limit|process error|Cannot start independent image Python/i);
  assert.equal(killAttempts,1);
  const second=call(f,'after-kill-denied','complete');second.catch(()=>{});
  await pause(30);
  assert.equal(writeStarts,1,'process-error after a kill request must not settle workerDone');
  assert.equal(fs.existsSync(f.file('finished-kill-denied')),false);
  fs.writeFileSync(f.file('release-kill-denied'),'release');
  assert.equal(result(await second).request_id,'after-kill-denied');
  await f.instance.queue;assert.equal(writeStarts,2);
});

test('inline PNG requires a workspace-contained regular bounded PNG; invalid images are never successful',async t=>{
  const f=fixture(t);
  const good=await call(f,'good-png','png');
  assert.equal(good.content[1].type,'image');assert.equal(good.content[1].mimeType,'image/png');
  assert.equal(Buffer.from(good.content[1].data,'base64').subarray(0,8).toString('hex'),'89504e470d0a1a0a');
  for(const [id,kind,reason] of [['outside','outside_png',/escapes workspace/],['large','large_png',/2 MiB/],['invalid','non_png',/not PNG/]])
    await assert.rejects(call(f,id,kind),reason);
});

test('wrong backend, noncompleted state, nonzero exit and pending records cannot return successful content',async t=>{
  const f=fixture(t);
  for(const [id,kind,reason] of [['backend','bad_backend',/completed external result/],['state','bad_state',/completed external result/],
    ['exit','nonzero_success',/failed/i],['pending','pending',/INCOMPLETE_REQUEST/]])
    await assert.rejects(call(f,id,kind),reason);
});
