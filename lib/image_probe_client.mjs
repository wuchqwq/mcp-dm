// One bounded read-only JSONL worker per configured ImageWorkspace. No journal
// entry per pointer query, no shared mutable scientific image, no DM access.
import {fileURLToPath} from 'node:url';
export function validateProbeResponse(result,parameters){
 const pair=value=>Array.isArray(value)&&value.length===2&&value.every(v=>typeof v==='number'&&Number.isFinite(v));
 const samples=result?.samples,grid=result?.scientific_grid_identity;
 if(result?.object_id!==parameters.object_id||result.backend!=='external-image-workspace'||result.state!=='completed'||result.kind!=='probe'||
  result.component!==(parameters.component??'raw')||!['source_pixels','source_array_indices','frequency_cycles_per_pixel'].includes(result.coordinate_space)||
  (parameters.coordinate_space!==undefined&&result.coordinate_space!==parameters.coordinate_space)||
  !Array.isArray(samples)||samples.length!==parameters.points?.length||samples.length<1||samples.length>64||
  !Array.isArray(grid?.shape_yx)||grid.shape_yx.length!==2||!grid.shape_yx.every(v=>Number.isSafeInteger(v)&&v>0)||
  grid.coordinate_space!==result.coordinate_space||!/^[a-f0-9]{64}$/.test(grid.array_sha256??'')||
  result.sampling?.interpolation!=='nearest'||result.sampling?.line_width!==1||
  samples.some((sample,i)=>!pair(sample.point)||!sample.point.every((v,j)=>v===parameters.points[i][j])||
   !pair(sample.array_index_xy)||!sample.array_index_xy.every((v,j)=>Number.isSafeInteger(v)&&v>=0&&v<grid.shape_yx[1-j])||
   !pair(sample.sampled_coordinate_xy)||typeof sample.value!=='number'||!Number.isFinite(sample.value)))throw new Error('Probe response identity, component, coordinates or numeric sample mismatch');
 return result;
}
export class ImageProbeClient {
 constructor({workspace,python,spawnProcess,workerPath=fileURLToPath(new URL('../tools/image_probe.py',import.meta.url))}){Object.assign(this,{workspace,python,spawnProcess,workerPath});this.sequence=0;this.pending=new Map();this.child=null;}
 start(){
  if(this.child)return;
  const child=this.spawnProcess(this.python,['-B',this.workerPath,this.workspace],{stdio:['pipe','pipe','pipe'],windowsHide:true});this.child=child;let buffer='',stderr='';
  const fail=error=>{if(this.child!==child)return;this.child=null;for(const value of this.pending.values())value.reject(error);this.pending.clear();};
  child.unref?.();
  child.stdout.on('data',chunk=>{buffer+=chunk.toString('utf8');if(Buffer.byteLength(buffer)>512*1024){child.kill();fail(new Error('Probe response exceeds bounded JSONL budget'));return;}let n;while((n=buffer.indexOf('\n'))>=0){const raw=buffer.slice(0,n);buffer=buffer.slice(n+1);try{const reply=JSON.parse(raw),waiting=this.pending.get(reply.serial);if(!waiting)continue;this.pending.delete(reply.serial);if(!reply.ok)waiting.reject(new Error(`${reply.error?.code??'PROBE_ERROR'}: ${reply.error?.message??'Probe failed'}`));else{try{validateProbeResponse(reply.result,waiting.parameters);waiting.resolve({content:[{type:'text',text:JSON.stringify(reply.result)}]});}catch(error){waiting.reject(error);}}}catch(error){child.kill();fail(error);}}if(!this.pending.size)this.refs(false);});
  child.stderr.on('data',chunk=>{stderr=(stderr+chunk.toString()).slice(-4096);});
  child.on('error',error=>fail(new Error('Cannot start read-only probe worker: '+error.message)));
  child.stdin.on('error',error=>fail(error));
  child.on('close',()=>fail(new Error('Read-only probe worker closed '+stderr)));
  this.refs(false);
 }
 refs(active){for(const stream of [this.child?.stdin,this.child?.stdout,this.child?.stderr])if(active)stream?.ref?.();else stream?.unref?.();}
 call(parameters){
  if(this.pending.size>=8)return Promise.reject(new Error('Read-only probe capacity exceeded; coalesce pointer requests'));
  this.start();const serial=++this.sequence,raw=JSON.stringify({serial,parameters});if(Buffer.byteLength(raw)>32768)return Promise.reject(new Error('Probe request exceeds 32 KiB'));
  this.refs(true);return new Promise((resolve,reject)=>{this.pending.set(serial,{resolve,reject,parameters:structuredClone(parameters)});this.child.stdin.write(raw+'\n');});
 }
 close(){this.child?.stdin.end();}
}
