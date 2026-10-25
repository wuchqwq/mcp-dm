
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
