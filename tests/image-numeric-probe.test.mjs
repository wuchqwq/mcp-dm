import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,readdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {ImageWorkspace} from '../lib/image_workspace.mjs';
import {validateProbeResponse} from '../lib/image_probe_client.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const python=process.env.DM_IMAGE_PYTHON||process.env.DM_TEST_PYTHON||'python';
function fixture(){
 const dir=mkdtempSync(path.join(tmpdir(),'image-probe-'));
 const response=spawnSync(python,['-c',String.raw`
import json,sys
from pathlib import Path
import numpy as np,tifffile
from tools.image_workspace import execute
base=Path(sys.argv[1]);source=base/'source.tiff';workspace=base/'workspace'
values=np.arange(35,dtype=np.uint16).reshape(5,7)
tifffile.imwrite(source,values,photometric='minisblack')
def call(action,request_id,**params):
 r=execute(dict(workspace=str(workspace),action=action,request_id=request_id,**params))
 if not r['ok']:raise RuntimeError(r)
 return r['result']
opened=call('open','open',source_path=str(source));frame=call('frame','frame',object_id=opened['object_id'],frame_index=0)
view=call('view','crop',object_id=frame['object_id'],rect=[2,1,6,5],gamma=3)
fft=call('fft','fft',object_id=frame['object_id'],window='none',subtract_mean=False)
print(json.dumps(dict(workspace=str(workspace),frame=frame,view=view,fft=fft)))
`,dir],{cwd:root,encoding:'utf8'});
 assert.equal(response.status,0,response.stderr||response.stdout);return {...JSON.parse(response.stdout),dir};
}
const value=reply=>JSON.parse(reply.content[0].text);
test('read-only samples reuse one real Python process, preserve source values and write no records',async()=>{
 const f=fixture(),children=[],spawnProcess=(...args)=>{const child=spawn(...args);children.push(child);return child;};
 const workspace=new ImageWorkspace({workspace:f.workspace,python,spawnProcess});
 try{
  const requests=readdirSync(path.join(f.workspace,'requests')),objects=readdirSync(path.join(f.workspace,'objects'));
  const first=value(await workspace.call('image_probe',{object_id:f.view.object_id,points:[[2,1],[3.5,2.5]],component:'raw'}));
  assert.deepEqual(first.samples.map(x=>x.value),[9,25]);assert.deepEqual(first.samples.map(x=>x.array_index_xy),[[0,0],[2,2]]);
  const args={object_id:f.view.object_id,points:[[2,1],[3.5,2.5]],component:'raw',coordinate_space:'source_pixels'};
  assert.equal(validateProbeResponse(first,args),first);
  for(const changed of [{...first,component:'power'},{...first,coordinate_space:'frequency_cycles_per_pixel'},{...first,samples:[...first.samples].reverse()},
   {...first,samples:[{...first.samples[0],value:null},first.samples[1]]},{...first,samples:[{...first.samples[0],value:Infinity},first.samples[1]]},
   {...first,samples:[{...first.samples[0],array_index_xy:[100,100]},first.samples[1]]}])assert.throws(()=>validateProbeResponse(changed,args),/mismatch/);
  const next=value(await workspace.call('image_probe',{object_id:f.frame.object_id,points:[[0,0],[6,4]]}));assert.deepEqual(next.samples.map(x=>x.value),[0,34]);
  const dc=value(await workspace.call('image_probe',{object_id:f.fft.object_id,points:[[0,0]],component:'amplitude'}));assert.equal(dc.samples[0].value,595);
  assert.equal(children.length,1);assert.equal(children[0].exitCode,null);
  assert.deepEqual(readdirSync(path.join(f.workspace,'requests')),requests);assert.deepEqual(readdirSync(path.join(f.workspace,'objects')),objects);
  await assert.rejects(workspace.call('image_probe',{object_id:f.frame.object_id,points:[[-.1,0]]}),/no clipping/);
  await assert.rejects(workspace.call('image_probe',{object_id:f.fft.object_id,points:[[0,0]],component:'raw'}),/Complex data requires/);
  await assert.rejects(workspace.call('image_probe',{object_id:f.frame.object_id,points:Array(65).fill([0,0])}),/1..64/);
  // A cached array does not bypass the provider's payload hash verification.
  const original=readFileSync(f.frame.array_path),changed=Buffer.from(original);changed[changed.length-1]^=1;writeFileSync(f.frame.array_path,changed);
  await assert.rejects(workspace.call('image_probe',{object_id:f.frame.object_id,points:[[0,0]]}),/Immutable object file changed/);
  assert.equal(children.length,1);writeFileSync(f.frame.array_path,original);
 }finally{const closing=children.map(child=>child.exitCode===null?new Promise(resolve=>child.once('close',resolve)):Promise.resolve());workspace.close();await Promise.all(closing);rmSync(f.dir,{recursive:true,force:true});}
});
