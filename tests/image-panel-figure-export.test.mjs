// Artifact and replay contracts only; browser PNG rendering is checked separately.
import test from 'node:test';
import assert from 'node:assert/strict';
import {buildFigureBundle,figureDimensions,figureScaleBar,figureZip,makeFigureRecipe,readFigureRecipe,figureDisplayParameters} from '../ui/image-panel/figure-export.mjs';

const copy=value=>JSON.parse(JSON.stringify(value));
function state(){return {effective_display:{gamma:1,display_range:[0,65535],max_size:512,upscale:false,interpolation:'lanczos',scale_bar:false},object:{object_id:'a'.repeat(32),panels:[{domain:'spatial_pixels',source_object_id:'b'.repeat(32),source_rect_xyxy:[16,8,528,392],image_rect_xyxy:[0,0,512,384]}],xy_calibration:{calibration_id:'c'.repeat(32),revision:1,status:'active',xy_scale:{x:.02,y:.02,unit:'nm'}},annotations:[{annotation_id:'peak-1',kind:'point',anchor:{source_object_id:'b'.repeat(32),coordinate_space:'source_pixels',coordinates:[80,60]},status:'user_confirmed',text:'g1',presentation:{marker_shape:'circle',label:{offset:[12,-24],text:'(1 -1 1)',pinned:true}}}]},frame_identity:{frame_index:0,frame_object_id:'d'.repeat(32)}};}
const preferences={preset:'diffraction',mode:'figure',columns:'single',fontPt:8,layers:{experimental:true,simulation_A:false,simulation_B:false},legend:false,scaleBar:false,letter:'a'};

test('figure recipe roundtrip changes only presentation and never its scientific source',()=>{
 const current=state(),before=copy(current),recipe=makeFigureRecipe(current,preferences);
 recipe.annotations[0].presentation.label.offset=[30,18];
 // Foreign scientific fields in a presentation entry cannot become an edit.
 recipe.annotations[0].coordinates=[900,900];recipe.annotations[0].status='hypothesized';
 const updates=readFigureRecipe(recipe,current);
 assert.deepEqual(updates,[{annotation_id:'peak-1',presentation:recipe.annotations[0].presentation}]);
 assert.deepEqual(current,before);assert.equal(current.object.annotations[0].status,'user_confirmed');
});

test('recipe refuses another source, physical calibration, anchor, status or pixel mapping',()=>{
 const original=state(),recipe=makeFigureRecipe(original,preferences);
 for(const mutate of [
  s=>s.object.panels[0].source_object_id='e'.repeat(32),
  s=>s.object.panels[0].image_rect_xyxy[2]=768,
  s=>s.object.annotations[0].anchor.coordinates[0]+=1,
  s=>s.object.annotations[0].status='hypothesized',
  s=>{s.object.xy_calibration.calibration_id='f'.repeat(32);s.object.xy_calibration.revision=2;s.object.xy_calibration.xy_scale.x=.04;}
 ]){const changed=copy(original);mutate(changed);assert.throws(()=>readFigureRecipe(recipe,changed),/科学|网格|标定/);}
});

test('recipe rejects unknown and duplicate stable references before queuing an edit',()=>{
 const current=state(),recipe=makeFigureRecipe(current,preferences);
 recipe.annotations.push(copy(recipe.annotations[0]));assert.throws(()=>readFigureRecipe(recipe,current),/重复|无效/);
 recipe.annotations=[{annotation_id:'foreign',presentation:{}}];assert.throws(()=>readFigureRecipe(recipe,current),/引用|无效/);
});

test('recipe requires complete explicit display controls and validates spectral treatment',()=>{
 const current=state(),recipe=makeFigureRecipe(current,preferences);
 for(const key of ['display_recipe','source_object_id']){const bad=copy(recipe);delete bad[key];assert.throws(()=>readFigureRecipe(bad,current),/显示/);}
 for(const [key,value]of [['gamma',NaN],['display_range',[5,1]],['max_size',2048],['upscale','yes'],['interpolation','cubic'],['scale_bar',null]]){const bad=copy(recipe);bad.display_recipe[key]=value;assert.throws(()=>readFigureRecipe(bad,current),/显示/);}
 for(const key of ['gamma','display_range','max_size','upscale','interpolation','scale_bar']){const bad=copy(recipe);delete bad.display_recipe[key];assert.throws(()=>readFigureRecipe(bad,current),/显示/);}
 const panel={domain:'frequency',fft_shape_yx:[64,96],fft_rect_xyxy:[8,4,64,48]},display={...current.effective_display,representation:'log_amplitude',spectrum_axes:false,spectrum_filter:null,frequency_rect:[8,4,64,48]};delete display.scale_bar;
 assert.deepEqual(figureDisplayParameters(display,[panel]),display);
 for(const patch of [{representation:'phase'},{frequency_rect:[0,0,97,64]},{spectrum_axes:'yes'},{spectrum_filter:{smooth_sigma_bins:2,background_sigma_bins:1}},{display_preset:'fft_detail',display_preset_revision:99}])assert.throws(()=>figureDisplayParameters({...display,...patch},[panel]),/显示/);
 assert.throws(()=>figureDisplayParameters({...display,representation:undefined},[panel]),/显示/);
});

test('physical scale bar is absent without an actual visible sourced bar record',()=>{
 assert.equal(figureScaleBar(null),null);assert.equal(figureScaleBar({visible:false,length:2,unit:'nm',image_endpoints_xyxy:[12,360,112,360]}),null);
 const record={visible:true,length:2,unit:'nm',image_endpoints_xyxy:[12,360,112,360],calibration_id:'actual-record'};
 const before=copy(record);assert.deepEqual(figureScaleBar(record),{x:12,y:360,length:100,label:'2 nm',color:'#fff'});assert.deepEqual(record,before);
});

test('single and double column export use a common aspect and bounded raster area',()=>{
 const single=figureDimensions(512,384),double=figureDimensions(512,384,'double');
 assert.deepEqual(single,{width:1004,height:753,width_mm:85,dpi:300});assert.equal(double.width,2126);assert.equal(double.height,1595);
 assert.throws(()=>figureDimensions(1,9000));assert.throws(()=>figureDimensions(0,2));
});

function zipEntries(bytes){
 const data=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),decoder=new TextDecoder(),files={};let offset=0;
 while(data.getUint32(offset,true)===0x04034b50){const size=data.getUint32(offset+18,true),nameLength=data.getUint16(offset+26,true),extraLength=data.getUint16(offset+28,true),name=decoder.decode(bytes.slice(offset+30,offset+30+nameLength)),start=offset+30+nameLength+extraLength;files[name]=bytes.slice(start,start+size);offset=start+size;}
 const end=bytes.length-22;assert.equal(data.getUint32(end,true),0x06054b50);assert.equal(data.getUint32(end+16,true),offset);assert.equal(data.getUint16(end+10,true),Object.keys(files).length);
 assert.equal(data.getUint32(offset,true),0x02014b50);return files;
}

test('four-file ZIP retains bytes and standard CRC32 with safe flat filenames',async()=>{
 const files={'clean.png':new Uint8Array([137,80,78,71]),'annotations.svg':'<svg>123456789</svg>','annotated.png':new Uint8Array([1,2,3]),'figure.json':'{}'};
 const data=new Uint8Array(await figureZip(files).arrayBuffer()),entries=zipEntries(data);
 assert.deepEqual(Object.keys(entries),Object.keys(files));assert.deepEqual(entries['clean.png'],files['clean.png']);assert.equal(new TextDecoder().decode(entries['figure.json']),'{}');
 const crcBytes=new Uint8Array(await figureZip({'known.txt':'123456789'}).arrayBuffer());assert.equal(new DataView(crcBytes.buffer).getUint32(14,true),0xcbf43926);
 assert.throws(()=>figureZip({'../escape.txt':'unsafe'}),/filename/);
});

test('bundle shares exact PNG/SVG mapping, escapes editable text and keeps source objects unchanged',async()=>{
 const current=state(),before=copy(current),mark={...current.object.annotations[0],coordinates:[64,52],presentation:{label:{text:'<script>alert("x")</script> & (1 -1 1)',offset:[16,8],pinned:true}}};
 const savedGlobals={Image:globalThis.Image,document:globalThis.document};let overlay='';
 globalThis.Image=class {constructor(){this.width=this.naturalWidth=512;this.height=this.naturalHeight=384;}async decode(){if(this.src.startsWith('blob:'))overlay=await(await fetch(this.src)).text();}};
 globalThis.document={createElement(tag){assert.equal(tag,'canvas');return {width:0,height:0,getContext(){return {drawImage(){},fillRect(){}};},toBlob(callback){callback(new Blob([Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jp1sAAAAASUVORK5CYII=','base64')],{type:'image/png'}));}};}};
 try{
  const result=await buildFigureBundle({state:current,marks:[mark],preferences,base64:'synthetic'});
  assert.deepEqual(Object.keys(result.files),['clean.png','annotations.svg','annotated.png','figure.json']);
  assert.deepEqual(current,before);assert.equal(result.recipe.source_object_id,current.object.object_id);
  assert.match(overlay,/viewBox="0 0 512 384"/);const tag=overlay.match(/^<svg\b[^>]*>/)[0];assert.equal((tag.match(/\swidth=/g)??[]).length,1);assert.equal((tag.match(/\sheight=/g)??[]).length,1);
  assert.match(tag,/width="85mm" height="63.75mm"/);assert.match(overlay,/<circle cx="64" cy="52"/);assert.doesNotMatch(overlay,/<script|<image\b/);assert.match(overlay,/&lt;script&gt;/);assert.match(overlay,/text-decoration="overline"/);assert.ok(zipEntries(new Uint8Array(await result.blob.arrayBuffer()))['figure.json']);
  const clean=result.files['clean.png'],phys=Buffer.from(clean).indexOf('pHYs');assert.ok(phys>0);assert.equal(new DataView(clean.buffer,clean.byteOffset+phys+4,9).getUint32(0),11811);
 }finally{if(savedGlobals.Image===undefined)delete globalThis.Image;else globalThis.Image=savedGlobals.Image;if(savedGlobals.document===undefined)delete globalThis.document;else globalThis.document=savedGlobals.document;}
});
