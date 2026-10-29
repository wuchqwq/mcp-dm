// Real exported stdio -> Python -> scientific arrays + local panel HTTP.
// No LLM, browser gestures, DM host, private specimen or native qualification.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,rmSync,readdirSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {StdioImageClient,createImagePanel} from '../tools/image_panel.mjs';
const dir=mkdtempSync(path.join(tmpdir(),'standalone-science-'));
const candidate=process.env.MICROSCOPY_PYTHON??(process.platform==='win32'?'python':'python3');
function runPython(code,args=[]){const result=spawnSync(candidate,['-B','-c',code,...args],{encoding:'utf8',env:{...process.env,PYTHONPATH:''}});if(result.error)throw result.error;assert.equal(result.status,0,result.stderr);return result.stdout.trim();}
const python=runPython('import sys;print(sys.executable)');
const source=path.join(dir,'source.tiff'),workspace=path.join(dir,'workspace'),output=path.join(dir,'export');
const hash=file=>createHash('sha256').update(readFileSync(file)).digest('hex');
let client,panel;
try{
  runPython("import numpy as np,tifffile,sys;a=np.arange(16*24,dtype=np.uint16).reshape(16,24);tifffile.imwrite(sys.argv[1],np.stack([a,a+100]),photometric='minisblack',metadata=None)",[source]);
  const original=hash(source);
  client=new StdioImageClient({workspace,python});
  const init=await client.rpc('initialize');assert.equal(init.result.serverInfo.name,'microscopy-core');
  let number=0;
  const call=async(name,args={})=>(await client.tool(name,{...args,request_id:'split-smoke-'+(++number)})).data;
  const opened=await call('image_open',{source_path:source});
  const frame=await call('image_frame',{object_id:opened.object_id,frame_index:0});
  const calibrated=await call('image_calibrate',{object_id:frame.object_id,scope:'image',xy_scale:{x:0.1,y:-0.2,unit:'nm'},source_text:'Synthetic migration test only: signed X=0.1, Y=-0.2 nm/pixel.'});
  const view=await call('image_preview',{object_id:calibrated.object_id,max_size:128});
  assert.ok(existsSync(path.join(workspace,'objects',view.object_id)),'exact caller workspace must be used');
  const fft=await call('image_fft',{object_id:calibrated.object_id,rect:[4,4,12,8],window:'none',subtract_mean:false,max_size:128});
  const measurement=await call('image_measure',{object_id:fft.object_id,coordinate_space:'frequency_cycles_per_pixel',points:[[0,0],[0.125,0]]});
  assert.ok(Math.abs(measurement.d_spacing-0.8)<1e-12,JSON.stringify(measurement));assert.equal(measurement.d_spacing_unit,'nm');
  await call('image_export',{object_id:fft.object_id,output_dir:output});
  const npys=readdirSync(output).filter(name=>name.endsWith('.npy'));assert.equal(npys.length,1);
  const npy=path.join(output,npys[0]),numericBefore=hash(npy);
  // Direct DFT uses the mathematical definition, not np.fft as a second oracle.
  runPython("import numpy as np,sys,cmath; a=np.arange(16*24,dtype=np.float64).reshape(16,24)[4:8,4:12]; h,w=a.shape; expected=np.array([[sum(a[y,x]*cmath.exp(-2j*cmath.pi*(u*y/h+v*x/w)) for y in range(h) for x in range(w)) for v in range(w)] for u in range(h)]);expected=np.roll(np.roll(expected,h//2,axis=0),w//2,axis=1);actual=np.load(sys.argv[1],allow_pickle=False);assert actual.dtype==np.complex128;assert actual.shape==(4,8);assert np.max(np.abs(actual-expected))<1e-9,(actual,expected)",[npy]);
  const revised=await call('image_preview',{object_id:fft.object_id,gamma:1.4,max_size:128});
  assert.notEqual(revised.object_id,fft.object_id);assert.equal(hash(npy),numericBefore);
  const originalRequest=fft.request_id;
  await client.close();client=new StdioImageClient({workspace,python});
  const recovered=(await client.tool('image_result',{request_id:originalRequest})).data;assert.equal(recovered.object_id,fft.object_id);
  panel=await createImagePanel({workspace,python,object_id:view.object_id});
  const response=await fetch(panel.url);assert.equal(response.status,200);assert.match(await response.text(),/<html/i);
  assert.equal(hash(source),original);
  console.log('PASS: standalone TIFF -> signed calibration -> ROI FFT -> 0.8 nm measurement -> NPY export/direct DFT -> display-only revision -> restart recovery -> panel HTTP; source unchanged.');
}finally{
  if(panel)await panel.close();
  if(client)await client.close();
  rmSync(dir,{recursive:true,force:true});
}
