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
  const names=(await c.rpc('tools/list')).result.tools.map(t=>t.name);assert.equal(names.length,15);assert.ok(names.includes('image_fft'));assert.ok(names.includes('image_calibrate'));assert.ok(names.includes('image_panel_current'));assert.ok(!names.includes('dm_status'));
  assert.ok((await c.tool('dm_status')).error,'standalone mode refuses DM tools');
  const invalid=await c.tool('image_open',{source_path:f.source});assert.equal(invalid.error.code,-32602);assert.equal(existsSync(f.workspace),false);
 }finally{await c.close();}
 const native=client(f.workspace,'native');try{const names=(await native.rpc('tools/list')).result.tools.map(t=>t.name);assert.equal(names.length,36);assert.ok(names.includes('dm_native_frame'));assert.ok(names.includes('image_preview'));assert.ok(names.includes('image_panel_open'));}finally{await native.close();rmSync(f.dir,{recursive:true,force:true});}
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

test('anchored overlays survive display revisions, export and fresh-client recovery through MCP',async()=>{
 const f=fixture();let c=client(f.workspace);try{
  const source=readFileSync(f.source);
  const opened=result(await c.tool('image_open',{source_path:f.source,request_id:'anchor-open'}));
  const frame=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:1,request_id:'anchor-frame'}));
  const v=result(await c.tool('image_preview',{object_id:frame.object_id,rect:[2,3,22,15],max_size:32,request_id:'anchor-view'}));
  const mark={annotation_id:'stripe-a',kind:'arrow',coordinate_space:'source_pixels',source_object_id:frame.object_id,coordinates:[4,5,18,12],status:'hypothesized',note:'Location candidate, not a twin claim'};
  const markedMessage=await c.tool('image_annotate',{object_id:v.object_id,annotations:[mark],request_id:'anchor-mark'});
  const marked=result(markedMessage);picture(markedMessage);
  const revisedMessage=await c.tool('image_preview',{object_id:marked.object_id,gamma:2,request_id:'anchor-gamma'});
  const revised=result(revisedMessage);picture(revisedMessage);
  assert.deepEqual(revised.annotations[0].anchor,{coordinate_space:mark.coordinate_space,source_object_id:frame.object_id,coordinates:mark.coordinates});
  assert.deepEqual(readFileSync(revised.array_path),readFileSync(v.array_path));
  const fftMessage=await c.tool('image_fft',{object_id:frame.object_id,rect:[2,3,22,15],window:'hann',subtract_mean:true,request_id:'anchor-fft'});
  const fft=result(fftMessage);picture(fftMessage);
  const frequencyMark={annotation_id:'frequency-a',kind:'line',coordinate_space:'frequency_cycles_per_pixel',source_object_id:fft.object_id,coordinates:[-.1,0,.1,0],status:'hypothesized'};
  const spectrumMark=result(await c.tool('image_annotate',{object_id:fft.object_id,annotations:[frequencyMark],request_id:'anchor-frequency'}));
  const rerenderMessage=await c.tool('image_preview',{object_id:spectrumMark.object_id,representation:'power',gamma:2,request_id:'anchor-power'});
  const rerender=result(rerenderMessage);picture(rerenderMessage);
  assert.equal(rerender.fft_recomputed,false);assert.equal(rerender.annotations[0].anchor.source_object_id,fft.object_id);
  const withdrawn=result(await c.tool('image_annotate',{object_id:rerender.object_id,annotations:[{...frequencyMark,status:'retracted'}],request_id:'anchor-withdraw'}));
  assert.equal(withdrawn.annotations[0].status,'retracted');
  const destination=path.join(f.dir,'anchor-export');
  result(await c.tool('image_export',{object_id:withdrawn.object_id,output_dir:destination,request_id:'anchor-export'}));
  assert.deepEqual(readFileSync(path.join(destination,'data.npy')),readFileSync(fft.array_path));
  const manifest=JSON.parse(readFileSync(path.join(destination,'manifest.json')));
  assert.equal(manifest.display_object.annotations[0].status,'retracted');
  assert.equal(manifest.display_object.annotations[0].anchor.source_object_id,fft.object_id);
  await c.close();c=client(f.workspace);
  const recoveredMessage=await c.tool('image_result',{request_id:'anchor-power'});
  assert.equal(result(recoveredMessage).object_id,rerender.object_id);picture(recoveredMessage);
  assert.equal((await c.tool('image_annotate',{object_id:rerender.object_id,annotations:[{...frequencyMark,source_object_id:frame.object_id}],request_id:'anchor-wrong-source'})).result.isError,true);
  assert.equal((await c.tool('image_annotate',{object_id:rerender.object_id,annotations:[{...frequencyMark,status:'confirmed_by_AI'}],request_id:'anchor-wrong-status'})).error.code,-32602);
  assert.deepEqual(readFileSync(f.source),source);
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

test('readable FFT presentation filters, axes and small arrows are actual MCP revisions',async()=>{
 const f=fixture();const c=client(f.workspace);try{
  const original=readFileSync(f.source);
  const opened=result(await c.tool('image_open',{source_path:f.source,request_id:'figure-open'}));
  const frame=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:1,request_id:'figure-frame'}));
  const fft=result(await c.tool('image_fft',{object_id:frame.object_id,window:'hann',subtract_mean:true,request_id:'figure-fft'}));
  const originalSpectrum=readFileSync(fft.array_path);
  const spec={smooth_sigma_bins:.5,background_sigma_bins:4};
  const message=await c.tool('image_preview',{object_id:fft.object_id,spectrum_filter:spec,spectrum_axes:true,upscale:true,max_size:512,request_id:'figure-filtered'});
  const view=result(message);picture(message);
  assert.deepEqual(view.display.spectrum_filter,spec);assert.equal(view.display.spectrum_axes,true);assert.equal(view.fft_recomputed,false);
  assert.deepEqual(view.panels[0].image_rect_xyxy.slice(0,2),[64,44]);
  const mark={annotation_id:'A',kind:'arrow',source_object_id:fft.object_id,coordinate_space:'frequency_cycles_per_pixel',coordinates:[.3,.2,.15,.1],status:'hypothesized',line_width:1,arrowhead_size:3};
  const marked=result(await c.tool('image_annotate',{object_id:view.object_id,annotations:[mark],request_id:'figure-small-arrow'}));
  const revisedMessage=await c.tool('image_preview',{object_id:marked.object_id,max_size:640,gamma:1.2,request_id:'figure-larger'});
  const revised=result(revisedMessage);picture(revisedMessage);
  assert.deepEqual(revised.display.spectrum_filter,spec);assert.equal(revised.annotations[0].arrowhead_size,3);
  assert.deepEqual(revised.annotations[0].anchor.coordinates,mark.coordinates);
  assert.deepEqual(readFileSync(revised.array_path),originalSpectrum);
  const restored=result(await c.tool('image_preview',{object_id:revised.object_id,spectrum_filter:null,spectrum_axes:false,request_id:'figure-unfiltered'}));
  assert.equal(restored.display.spectrum_filter,null);assert.deepEqual(readFileSync(restored.array_path),originalSpectrum);
  assert.equal((await c.tool('image_preview',{object_id:frame.object_id,spectrum_filter:spec,request_id:'figure-wrong-domain'})).result.isError,true);
  assert.equal((await c.tool('image_preview',{object_id:fft.object_id,spectrum_filter:{smooth_sigma_bins:2,background_sigma_bins:1},request_id:'figure-invalid-filter'})).result.isError,true);
  assert.equal((await c.tool('image_preview',{object_id:fft.object_id,spectrum_axes:true,max_size:128,request_id:'figure-too-small'})).result.isError,true);
  assert.equal((await c.tool('image_annotate',{object_id:view.object_id,annotations:[{...mark,arrowhead_size:100}],request_id:'figure-oversize-arrow'})).error.code,-32602);
  const detailMessage=await c.tool('image_preview',{object_id:revised.object_id,display_preset:'fft_detail',request_id:'figure-detail-preset'});
  const detail=result(detailMessage);picture(detailMessage);
  assert.equal(detail.display.spectrum_filter,null);assert.equal(detail.display.spectrum_axes,false);
  assert.equal(detail.display.range_source,'percentile');assert.deepEqual(detail.display.range_percentiles,[5,99.8]);
  assert.deepEqual(readFileSync(detail.array_path),originalSpectrum);
  const whiteMessage=await c.tool('image_annotate',{object_id:detail.object_id,annotations:[{...mark,color:'white'}],request_id:'figure-white-candidate'});
  const white=result(whiteMessage);picture(whiteMessage);
  assert.equal(white.annotations[0].color,'white');assert.equal(white.annotations[0].status,'hypothesized');
  const inheritedWhite=result(await c.tool('image_preview',{object_id:white.object_id,gamma:.9,request_id:'figure-white-revision'}));
  assert.equal(inheritedWhite.annotations[0].color,'white');assert.equal(inheritedWhite.display.spectrum_filter,null);
  assert.equal((await c.tool('image_preview',{object_id:frame.object_id,display_preset:'fft_detail',request_id:'figure-preset-wrong-domain'})).result.isError,true);
  assert.deepEqual(readFileSync(f.source),original);
 }finally{await c.close();rmSync(f.dir,{recursive:true,force:true});}
});

test('frequency zoom preserves original bins, full complex export and anchored marks across MCP clients',async()=>{
 const f=fixture();let c=client(f.workspace);try{
  const source=readFileSync(f.source);
  const opened=result(await c.tool('image_open',{source_path:f.source,request_id:'zoom-open'}));
  const frame=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:1,request_id:'zoom-frame'}));
  const fft=result(await c.tool('image_fft',{object_id:frame.object_id,rect:[2,3,22,15],window:'hann',request_id:'zoom-fft'}));
  const raw=readFileSync(fft.array_path);
  const detail=result(await c.tool('image_preview',{object_id:fft.object_id,display_preset:'fft_detail',request_id:'zoom-full'}));
  assert.equal(detail.display.gamma,.8);assert.equal(detail.display.display_preset_revision,2);
  const mark={annotation_id:'candidate-a',kind:'arrow',color:'white',line_width:1,arrowhead_size:2,
   coordinate_space:'frequency_cycles_per_pixel',source_object_id:fft.object_id,coordinates:[.25,.25,.2,1/6],status:'hypothesized'};
  const annotated=result(await c.tool('image_annotate',{object_id:detail.object_id,annotations:[mark],request_id:'zoom-annotate'}));
  const zoomArgs={object_id:annotated.object_id,frequency_rect:[12,6,18,11],max_size:256,interpolation:'nearest',request_id:'zoom-saved'};
  const zoomMessage=await c.tool('image_preview',zoomArgs);const zoom=result(zoomMessage);picture(zoomMessage);
  assert.deepEqual(zoom.panels[0].fft_shape_yx,[12,20]);assert.deepEqual(zoom.panels[0].fft_rect_xyxy,[12,6,18,11]);
  assert.deepEqual(zoom.panels[0].image_rect_xyxy,[0,0,256,213]);
  assert.equal(zoom.spectrum_object_id,fft.object_id);assert.equal(zoom.fft_recomputed,false);
  assert.equal(zoom.display.interpolation,'nearest');
  assert.deepEqual(zoom.frequency_axes,fft.frequency_axes);assert.deepEqual(zoom.display.display_range,detail.display.display_range);
  assert.deepEqual(zoom.annotations[0].anchor.coordinates,mark.coordinates);
  assert.ok(Math.abs(zoom.annotations[0].coordinates[2]-(2.5*256/6-.5))<1e-10);
  assert.ok(Math.abs(zoom.annotations[0].coordinates[3]-(2.5*213/5-.5))<1e-10);
  assert.deepEqual(readFileSync(zoom.array_path),raw);
  const dest=path.join(f.dir,'frequency-zoom-export');
  result(await c.tool('image_export',{object_id:zoom.object_id,output_dir:dest,request_id:'zoom-export'}));
  assert.deepEqual(readFileSync(path.join(dest,'data.npy')),raw);
  const manifest=JSON.parse(readFileSync(path.join(dest,'manifest.json')));
  assert.deepEqual(manifest.display_mapping.frequency_rect,[12,6,18,11]);assert.deepEqual(manifest.scientific_object.shape_yx,[12,20]);
  await c.close();c=client(f.workspace);
  const recoveredMessage=await c.tool('image_result',{request_id:'zoom-saved'});
  assert.equal(result(recoveredMessage).object_id,zoom.object_id);picture(recoveredMessage);
  assert.equal(result(await c.tool('image_preview',zoomArgs)).object_id,zoom.object_id);
  assert.equal((await c.tool('image_preview',{...zoomArgs,frequency_rect:[0,0,2,2]})).result.isError,true);
  const reset=result(await c.tool('image_preview',{object_id:zoom.object_id,frequency_rect:null,request_id:'zoom-reset'}));
  assert.deepEqual(reset.display.frequency_rect,[0,0,20,12]);assert.equal(reset.annotations[0].visibility,'visible');
  assert.equal((await c.tool('image_preview',{object_id:frame.object_id,frequency_rect:[0,0,2,2],request_id:'zoom-wrong-domain'})).result.isError,true);
  assert.equal((await c.tool('image_preview',{object_id:fft.object_id,frequency_rect:[0,0,21,12],request_id:'zoom-outside'})).result.isError,true);
  assert.equal((await c.tool('image_preview',{object_id:fft.object_id,frequency_rect:[0,0,1.5,2],request_id:'zoom-fraction'})).error.code,-32602);
  assert.equal((await c.tool('image_preview',{object_id:fft.object_id,interpolation:'auto-sharpen',request_id:'zoom-unknown-interpolation'})).error.code,-32602);
  assert.deepEqual(readFileSync(f.source),source);
 }finally{await c.close();rmSync(f.dir,{recursive:true,force:true});}
});

test('short cyan and optional orange arrows preserve source anchors through actual MCP revisions',async()=>{
 const f=fixture();let c=client(f.workspace);try{
  const source=readFileSync(f.source);
  const opened=result(await c.tool('image_open',{source_path:f.source,request_id:'style-open'}));
  const frame=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:1,request_id:'style-frame'}));
  const fft=result(await c.tool('image_fft',{object_id:frame.object_id,window:'hann',request_id:'style-fft'}));
  const raw=readFileSync(fft.array_path);
  const view=result(await c.tool('image_preview',{object_id:fft.object_id,display_preset:'fft_detail',request_id:'style-view'}));
  const primary={annotation_id:'primary-candidate',kind:'arrow',coordinate_space:'frequency_cycles_per_pixel',
   source_object_id:fft.object_id,coordinates:[-.25,-.25,.25,.25],status:'hypothesized'};
  const secondary={...primary,annotation_id:'secondary-candidate',coordinates:[-.2,.2,.2,-.2],color:'orange',
   note:'Second-phase candidate is a proposed interpretation, not a confirmed phase'};
  const markedMessage=await c.tool('image_annotate',{object_id:view.object_id,annotations:[primary,secondary],request_id:'style-mark'});
  const marked=result(markedMessage);picture(markedMessage);
  const length=coords=>Math.hypot(coords[2]-coords[0],coords[3]-coords[1]);
  for(const [i,input] of [primary,secondary].entries()){
   const mark=marked.annotations[i];
   assert.equal(mark.color,i===0?'cyan':'orange');assert.equal(mark.status,'hypothesized');
   assert.equal(mark.line_width,3);assert.equal(mark.arrowhead_size,6);assert.equal(mark.arrow_length,24);
   assert.ok(Math.abs(length(mark.arrow_render_coordinates)-24)<1e-10);
   assert.ok(length(mark.coordinates)>24);
   assert.deepEqual(mark.arrow_render_coordinates.slice(2),mark.coordinates.slice(2));
   assert.deepEqual(mark.anchor,{coordinate_space:input.coordinate_space,source_object_id:fft.object_id,coordinates:input.coordinates});
   assert.deepEqual(mark.source_mappings[0].frequency_cycles_per_pixel,input.coordinates);
  }
  const resizedMessage=await c.tool('image_preview',{object_id:marked.object_id,max_size:768,gamma:.9,request_id:'style-resize'});
  const resized=result(resizedMessage);picture(resizedMessage);
  for(let i=0;i<2;i++){
   assert.deepEqual(resized.annotations[i].anchor,marked.annotations[i].anchor);
   assert.ok(Math.abs(length(resized.annotations[i].arrow_render_coordinates)-24)<1e-10);
   assert.equal(resized.annotations[i].color,marked.annotations[i].color);
   assert.equal(resized.annotations[i].status,'hypothesized');
   assert.deepEqual(resized.annotations[i].arrow_render_coordinates.slice(2),resized.annotations[i].coordinates.slice(2));
  }
  assert.deepEqual(readFileSync(resized.array_path),raw);
  const full=result(await c.tool('image_annotate',{object_id:resized.object_id,annotations:[{...primary,arrow_length:null}],request_id:'style-full'}));
  assert.equal(full.annotations[0].arrow_length,null);
  assert.deepEqual(full.annotations[0].arrow_render_coordinates,full.annotations[0].coordinates);
  assert.ok(length(full.annotations[0].arrow_render_coordinates)>24);
  for(const [i,value] of [3,129,4.5,true,'24'].entries()){
   const invalid=await c.tool('image_annotate',{object_id:view.object_id,annotations:[{...primary,arrow_length:value}],request_id:'style-invalid-'+i});
   assert.equal(invalid.error.code,-32602);
  }
  const wrongKind=await c.tool('image_annotate',{object_id:view.object_id,annotations:[{...primary,kind:'line',arrow_length:24}],request_id:'style-line-cap'});
  assert.equal(wrongKind.result.isError,true);
  const dest=path.join(f.dir,'short-arrow-export');
  result(await c.tool('image_export',{object_id:resized.object_id,output_dir:dest,request_id:'style-export'}));
  assert.deepEqual(readFileSync(path.join(dest,'data.npy')),raw);
  const manifest=JSON.parse(readFileSync(path.join(dest,'manifest.json')));
  assert.deepEqual(manifest.display_object.annotations,resized.annotations);
  assert.deepEqual(readFileSync(path.join(dest,'preview.png')),readFileSync(resized.image_path));
  await c.close();c=client(f.workspace);
  const recoveredMessage=await c.tool('image_result',{request_id:'style-resize'});picture(recoveredMessage);
  const recovered=result(recoveredMessage);
  assert.equal(recovered.object_id,resized.object_id);assert.deepEqual(recovered.annotations,resized.annotations);
  assert.deepEqual(readFileSync(f.source),source);assert.deepEqual(readFileSync(fft.array_path),raw);
 }finally{await c.close();rmSync(f.dir,{recursive:true,force:true});}
});

test('user-stated sequence XY calibration updates physical geometry/axes without recomputing saved FFT and survives a fresh MCP client',async()=>{
 const f=fixture();let c=client(f.workspace);try{
  const sourceBefore=readFileSync(f.source);
  const opened=result(await c.tool('image_open',{source_path:f.source,request_id:'cal-open'}));
  const frame=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:0,request_id:'cal-frame'}));
  const fft=result(await c.tool('image_fft',{object_id:frame.object_id,rect:[2,2,18,10],request_id:'cal-fft'}));
  const savedFFT=readFileSync(fft.array_path);
  const args={object_id:opened.object_id,scope:'sequence',xy_scale:{x:.2,y:-.5,unit:'nm'},source_text:'Synthetic user explicitly specifies signed X=.2nm/px,Y=-.5nm/px for this sequence; uncertainty unknown',request_id:'cal-statement'};
  const record=result(await c.tool('image_calibrate',args));
  assert.equal(record.xy_calibration.scope,'sequence');assert.equal(record.xy_calibration.uncertainty_status,'unknown');
  assert.equal(record.xy_calibration.applies_to.object_id,opened.object_id);
  await c.close();c=client(f.workspace);
  const recovered=result(await c.tool('image_result',{request_id:'cal-statement'}));
  assert.equal(recovered.object_id,record.object_id);
  assert.equal(result(await c.tool('image_calibrate',args)).object_id,record.object_id);
  const calibratedFrame=result(await c.tool('image_frame',{object_id:record.object_id,frame_index:1,request_id:'cal-frame2'}));
  assert.deepEqual(calibratedFrame.xy_calibration,record.xy_calibration);
  const viewMessage=await c.tool('image_preview',{object_id:calibratedFrame.object_id,max_size:320,upscale:true,request_id:'cal-preview'});
  const view=result(viewMessage);picture(viewMessage);assert.equal(view.scale_bar.unit,'nm');assert.equal(view.scale_bar.visible,true);
  const physical=result(await c.tool('image_measure',{object_id:view.object_id,points:[[0,0],[3,4]],request_id:'cal-length'}));
  assert.ok(Math.abs(physical.physical_distance-Math.hypot(.6,2))<1e-12);assert.equal(physical.physical_unit,'nm');
  assert.ok(Math.abs(physical.physical_angle_degrees-Math.atan2(-2,.6)*180/Math.PI)<1e-12);
  const attached=result(await c.tool('image_calibrate',{object_id:fft.object_id,calibration_object_id:record.object_id,request_id:'cal-attach'}));
  const axesMessage=await c.tool('image_preview',{object_id:attached.object_id,spectrum_axes:true,max_size:512,upscale:true,request_id:'cal-axes'});
  const axes=result(axesMessage);picture(axesMessage);assert.equal(axes.display.axis_labels_unit,'cycles/nm');assert.equal(axes.fft_recomputed,false);
  assert.deepEqual(readFileSync(axes.array_path),savedFFT);
  const frequency=result(await c.tool('image_measure',{object_id:axes.object_id,coordinate_space:'frequency_cycles_per_pixel',points:[[0,0],[.125,.25]],request_id:'cal-period'}));
  assert.ok(Math.abs(frequency.d_spacing-1/Math.hypot(.625,.5))<1e-12);assert.equal(frequency.d_spacing_unit,'nm');
  assert.equal(frequency.calibration_dependency.calibration_id,record.object_id);
  const output=path.join(f.dir,'calibrated-fft');
  result(await c.tool('image_export',{object_id:axes.object_id,output_dir:output,request_id:'cal-export'}));
  assert.deepEqual(readFileSync(path.join(output,'data.npy')),savedFFT);
  const manifest=JSON.parse(readFileSync(path.join(output,'manifest.json')));
  assert.deepEqual(manifest.xy_calibration,record.xy_calibration);assert.equal(manifest.display_mapping.axis_labels_unit,'cycles/nm');
  const withdrawn=result(await c.tool('image_calibrate',{object_id:axes.object_id,scope:'sequence',xy_scale:null,source_text:'Synthetic user withdraws the estimate',request_id:'cal-withdraw'}));
  assert.equal(withdrawn.xy_calibration.revision,2);assert.equal(withdrawn.xy_calibration.status,'withdrawn');
  const stale=await c.tool('image_export',{object_id:withdrawn.object_id,output_dir:path.join(f.dir,'stale-export'),request_id:'cal-stale'});
  assert.equal(stale.result.isError,true);assert.equal(existsSync(path.join(f.dir,'stale-export')),false);
  const pixelMessage=await c.tool('image_preview',{object_id:withdrawn.object_id,spectrum_axes:true,request_id:'cal-pixel-axes'});
  const pixel=result(pixelMessage);picture(pixelMessage);assert.equal(pixel.display.axis_labels_unit,'cycles/pixel');assert.equal(pixel.physical_frequency_unit,null);
  const pixelFrequency=result(await c.tool('image_measure',{object_id:pixel.object_id,points:[[0,0],[.125,0]],request_id:'cal-pixel-period'}));
  assert.equal(pixelFrequency.pixel_period,8);assert.equal(pixelFrequency.d_spacing,null);
  assert.deepEqual(readFileSync(f.source),sourceBefore);assert.deepEqual(readFileSync(fft.array_path),savedFFT);
 }finally{await c.close();rmSync(f.dir,{recursive:true,force:true});}
});

test('calibration schema/refusal gates require request identity, provenance, units and exact scope',async()=>{
 const f=fixture();const c=client(f.workspace);try{
  const opened=result(await c.tool('image_open',{source_path:f.source,request_id:'cal-bad-open'}));
  const frame=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:0,request_id:'cal-bad-frame'}));
  const base={object_id:frame.object_id,scope:'image',xy_scale:{x:.2,y:.2,unit:'nm'},source_text:'Synthetic explicit user statement'};
  assert.equal((await c.tool('image_calibrate',base)).error.code,-32602);
  assert.equal((await c.tool('image_calibrate',{...base,xy_scale:{x:1,y:1,unit:'radians'},request_id:'cal-bad-unit'})).error.code,-32602);
  assert.equal((await c.tool('image_calibrate',{...base,xy_scale:{x:1,unit:'nm'},request_id:'cal-bad-xy'})).error.code,-32602);
  assert.equal((await c.tool('image_calibrate',{...base,xy_scale:{x:0,y:1,unit:'nm'},request_id:'cal-zero'})).result.isError,true);
  assert.equal((await c.tool('image_calibrate',{...base,source_text:' ',request_id:'cal-no-provenance'})).result.isError,true);
  const record=result(await c.tool('image_calibrate',{...base,request_id:'cal-image'}));
  const other=result(await c.tool('image_frame',{object_id:opened.object_id,frame_index:1,request_id:'cal-other'}));
  assert.equal((await c.tool('image_calibrate',{object_id:other.object_id,calibration_object_id:record.object_id,request_id:'cal-other-attach'})).result.isError,true);
  assert.equal((await c.tool('image_calibrate',{...base,xy_scale:{x:.4,y:.4,unit:'nm'},request_id:'cal-image'})).result.isError,true);
 }finally{await c.close();rmSync(f.dir,{recursive:true,force:true});}
});
