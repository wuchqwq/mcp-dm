import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import vm from 'node:vm';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {createStructureViewer,validateStructureSnapshot,read3DmolAsset,STRUCTURE_VIEWER_VERSION,STRUCTURE_CONTACT_POLICY,inspectRendererContacts} from '../tools/structure_viewer.mjs';
const structure=()=>({object_id:'a'.repeat(32),symbols:['C','Si'],positions_angstrom:[[0,0,0],[1.1,-.3,.7]],cell_angstrom:[[2,0,0],[.3,3,0],[.2,.4,4]],pbc:[true,true,true]});
function fixture(){
 const directory=mkdtempSync(path.join(tmpdir(),'mcp-structure-viewer-')),packageDirectory=path.join(directory,'node_modules','3dmol'),assetPath=path.join(packageDirectory,'build','3Dmol-min.js');mkdirSync(path.dirname(assetPath),{recursive:true});
 // This is a transport fixture, not a WebGL or real 3Dmol qualification.
 writeFileSync(assetPath,'/* offline transport fixture; not a rendered viewer */');writeFileSync(path.join(packageDirectory,'package.json'),JSON.stringify({name:'3dmol',version:STRUCTURE_VIEWER_VERSION,license:'BSD-3-Clause'}));writeFileSync(path.join(packageDirectory,'LICENSE'),'BSD-3-Clause fixture license');
 return {directory,packageDirectory,assetPath,close(){rmSync(directory,{recursive:true,force:true});}};
}
function manyAtoms(count){const s=structure();s.symbols=Array(count).fill('C');s.positions_angstrom=Array.from({length:count},(_,i)=>[i,0,0]);return s;}
function graphAtoms(snapshot,edges){
 const atoms=snapshot.symbols.map((elem,i)=>({elem,index:i,x:snapshot.positions_angstrom[i][0],y:snapshot.positions_angstrom[i][1],z:snapshot.positions_angstrom[i][2],bonds:[],bondOrder:[]}));
 for(const [a,b]of edges){atoms[a].bonds.push(b);atoms[a].bondOrder.push(1);atoms[b].bonds.push(a);atoms[b].bondOrder.push(1);}
 return atoms;
}
function firstEdges(count,limit){const edges=[];for(let a=0;a<count;a++)for(let b=a+1;b<count;b++){if(edges.length===limit)return edges;edges.push([a,b]);}return edges;}
// A public-API component double tests the adapter contract, not real 3Dmol's
// distance calculation, WebGL or scientific chemistry.
async function browserHarness(source=structure(),{edges=[[0,1]],afterAssign,missingAssign=false}={}){
 const f=fixture(),service=await createStructureViewer({structure:source,assetPath:f.assetPath});
 try{
  const origin=service.url.split('/#')[0],script=await(await fetch(origin+'/viewer.mjs')).text(),data=await(await fetch(origin+'/api/structure',{headers:{'X-Viewer-Token':service.token}})).json();
  const elements=new Map(),calls={assign:0,zoom:0,remove:0,styles:[]};let atoms=[],view=[0,0,0,-10,0,0,0,1];
  const el=id=>{if(!elements.has(id))elements.set(id,{textContent:'',value:'',disabled:true});return elements.get(id);};
  const model={addAtoms(values){atoms.push(...values.map((a,i)=>({...a,index:i,bonds:[...a.bonds],bondOrder:[...a.bondOrder]})));},selectedAtoms(){return atoms;},removeAtoms(){calls.remove++;atoms=[];},setCrystMatrix(matrix){calls.matrix=matrix.values;},assignBonds(){calls.assign++;const graph=graphAtoms(data.structure,edges);atoms.forEach((a,i)=>{a.bonds=graph[i].bonds;a.bondOrder=graph[i].bondOrder;});afterAssign?.(atoms);}};
  if(missingAssign)delete model.assignBonds;
  const viewer={addModel(){return model;},setStyle(a,b){calls.styles.push(b);view=[0,0,0,-99,0,0,0,1];},addUnitCell(){calls.cell=true;},addArrow(spec){(calls.arrows??=[]).push(spec);},zoomTo(){calls.zoom++;view=[0,0,0,-10,0,0,0,1];},render(){},getView(){return [...view];},setView(value){view=[...value];},setViewChangeCallback(fn){calls.camera=fn;},resize(){}};
  const sandbox={document:{getElementById:el},sessionStorage:{setItem(){},getItem(){return service.token;}},location:{hash:'#'+service.token,pathname:'/'},history:{replaceState(){}},window:{addEventListener(){}},fetch:async()=>({ok:true,json:async()=>data}),$3Dmol:{createViewer(){return viewer;},Matrix3:class{constructor(...values){this.values=values;}}}};
  await vm.runInNewContext('(async()=>{'+script+'})()',sandbox);
  return {data,el,calls,get atoms(){return atoms;},get view(){return view;},set view(value){view=[...value];},change(mode){el('display-mode').value=mode;el('display-mode').onchange();},async close(){await service.close();f.close();}};
 }catch(error){await service.close();f.close();throw error;}
}
test('typed ASE snapshot preserves Cartesian positions, signed axes and independent ownership',()=>{
 const source=structure(),before=JSON.stringify(source),snapshot=validateStructureSnapshot(source);assert.deepEqual(snapshot.cell_angstrom,source.cell_angstrom);assert.equal(snapshot.coordinate_unit,'angstrom');assert.equal(snapshot.cell_drawn,true);snapshot.positions_angstrom[1][0]=99;assert.equal(JSON.stringify(source),before);
});
test('finite known atoms, position shape and work budget are checked before serving',()=>{
 const invalid=[s=>{s.symbols[0]='<script>'},s=>{s.symbols[0]='X'},s=>{s.symbols=[];s.positions_angstrom=[];},s=>{s.positions_angstrom[0][0]=NaN;},s=>{s.positions_angstrom[0][1]=Infinity;},s=>{s.positions_angstrom[0][2]=1e7;},s=>{s.positions_angstrom[0]=[1,2]},s=>{s.positions_angstrom[0][0]='1'},s=>{s.object_id='latest'},s=>{s.script='unsafe'},s=>{s.pbc=[true,0,true]},s=>{s.cell_angstrom[2][0]=Infinity}];
 for(const mutate of invalid){const s=structure();mutate(s);assert.throws(()=>validateStructureSnapshot(s));}
 const s=structure();s.symbols=Array(4096).fill('C');s.positions_angstrom=Array.from({length:4096},(_,i)=>[i,0,0]);assert.equal(validateStructureSnapshot(s).atom_count,4096);s.symbols.push('C');s.positions_angstrom.push([4096,0,0]);assert.throws(()=>validateStructureSnapshot(s),/4096/);
});
test('no-cell XYZ remains viewable without inventing periodicity or a cell',()=>{
 const s=structure();s.cell_angstrom=Array.from({length:3},()=>[0,0,0]);s.pbc=[false,false,false];assert.equal(validateStructureSnapshot(s).cell_drawn,false);s.pbc[0]=true;assert.throws(()=>validateStructureSnapshot(s),/actual nonzero/);
});
test('partial periodic cells retain only actual independent directions and never require a fictitious third vector',()=>{
 const s=structure();s.cell_angstrom=[[3,0,0],[-1,2,0],[0,0,0]];s.pbc=[true,true,false];const before=JSON.stringify(s),out=validateStructureSnapshot(s);
 assert.equal(out.cell_drawn,false);assert.equal(out.cell_display,'declared_periodic_vectors_only');assert.deepEqual(out.periodic_cell_axes,[0,1]);assert.deepEqual(out.cell_angstrom[2],[0,0,0]);assert.equal(JSON.stringify(s),before);
 s.pbc=[true,false,false];assert.deepEqual(validateStructureSnapshot(s).periodic_cell_axes,[0]);s.cell_angstrom[0]=[0,0,0];assert.throws(()=>validateStructureSnapshot(s),/actual nonzero/);
 s.cell_angstrom=[[3,0,0],[6,0,0],[0,0,0]];s.pbc=[true,true,false];assert.throws(()=>validateStructureSnapshot(s),/independent/);
});
test('partial-cell presentation draws actual periodic vectors without synthesizing a three-dimensional unit cell',async()=>{
 const s=structure();s.cell_angstrom=[[3,0,0],[-1,2,0],[0,0,0]];s.pbc=[true,true,false];const h=await browserHarness(s);try{
  assert.equal(h.calls.cell,undefined);assert.equal(h.calls.matrix,undefined);assert.equal(h.calls.arrows.length,2);assert.deepEqual(JSON.parse(JSON.stringify(h.calls.arrows.map(a=>a.end))),[{x:3,y:0,z:0},{x:-1,y:2,z:0}]);
  assert.match(h.el('summary').textContent,/2 个已知周期方向/);assert.deepEqual(h.data.structure.cell_angstrom,s.cell_angstrom);
 }finally{await h.close();}
});
test('optional local mature renderer must exist with pinned package metadata; absence is not a 3D success',async()=>{
 await assert.rejects(createStructureViewer({structure:structure(),assetPath:path.resolve('missing-3dmol/3Dmol-min.js')}));const f=fixture();try{const a=read3DmolAsset(f.assetPath);assert.equal(a.version,STRUCTURE_VIEWER_VERSION);assert.match(a.sha256,/^[a-f0-9]{64}$/);writeFileSync(path.join(f.packageDirectory,'package.json'),JSON.stringify({name:'3dmol',version:'0.0.0',license:'BSD-3-Clause'}));assert.throws(()=>read3DmolAsset(f.assetPath),/pinned/);}finally{f.close();}
});
test('loopback transport refuses missing token, wrong Host/Origin, writes and arbitrary paths',async()=>{
 const f=fixture();let viewer;try{
  viewer=await createStructureViewer({structure:structure(),assetPath:f.assetPath});const origin=viewer.url.split('/#')[0],headers={'X-Viewer-Token':viewer.token,Origin:origin};
  assert.equal((await fetch(origin+'/api/structure')).status,403);assert.equal((await fetch(origin+'/api/structure',{headers:{...headers,Origin:'https://example.invalid'}})).status,403);
  const wrongHost=await new Promise((resolve,reject)=>{const request=http.get(origin+'/api/structure',{headers:{...headers,Host:'localhost:'+viewer.server.address().port}},response=>{response.resume();resolve(response.statusCode);});request.on('error',reject);});assert.equal(wrongHost,403);
  assert.equal((await fetch(origin+'/api/structure',{method:'POST',headers,body:'{}'})).status,405);assert.equal((await fetch(origin+'/server.mjs',{headers})).status,404);assert.equal((await fetch(origin+'/api/structure?script=unsafe',{headers})).status,404);
  const response=await fetch(origin+'/api/structure',{headers}),data=await response.json();assert.equal(response.status,200);assert.deepEqual(data.structure.positions_angstrom,structure().positions_angstrom);assert.deepEqual(data.structure.cell_angstrom,structure().cell_angstrom);assert.equal(data.read_only,true);assert.equal(data.renderer.name,'3Dmol.js');
  const page=await (await fetch(origin+'/')).text();assert.ok(!page.includes(structure().object_id));assert.ok(!page.includes('positions_angstrom'));assert.match(page,/3Dmol-min\.js/);assert.match(page,/缺项用组件默认 1\.6 Å/);assert.match(response.headers.get('content-security-policy'),/connect-src 'self'/);
  assert.equal((await fetch(origin+'/3Dmol-min.js')).status,200);assert.equal((await fetch(origin+'/LICENSE-3Dmol.txt')).status,200);
 }finally{await viewer?.close();f.close();}
});
test('owned helper closure needs explicit POST, exact token/origin and snapshot identity; a closing acknowledgement is not an exit receipt',async()=>{
 const f=fixture();let service,closed;
 try{
  service=await createStructureViewer({structure:structure(),assetPath:f.assetPath,onClosed:record=>{closed=record;}});
  const origin=service.url.split('/#')[0],headers={'X-Viewer-Token':service.token,Origin:origin,'Content-Type':'application/json'},command={request_id:'close-test',object_id:structure().object_id,snapshot_sha256:service.snapshot_sha256},body=JSON.stringify(command);
  assert.equal((await fetch(origin+'/api/close')).status,405);
  assert.equal((await fetch(origin+'/api/close',{method:'POST',headers:{...headers,'X-Viewer-Token':'0'.repeat(48)},body})).status,403);
  assert.equal((await fetch(origin+'/api/close',{method:'POST',headers:{...headers,Origin:'https://foreign.invalid'},body})).status,403);
  assert.equal((await fetch(origin+'/api/close',{method:'POST',headers,body:JSON.stringify({...command,snapshot_sha256:'0'.repeat(64)})})).status,400);
  assert.equal((await fetch(origin+'/api/close',{method:'POST',headers,body:body.replace('"close-test"','"close-test","request_id":"close-test"')})).status,400);
  assert.equal((await fetch(origin+'/api/structure',{headers})).status,200);assert.equal(closed,undefined);
  const ack=await(await fetch(origin+'/api/close',{method:'POST',headers,body})).json();assert.equal(ack.state,'closing');assert.notEqual(ack.state,'closed');await service.close('close-test');assert.equal(closed.state,'closed');assert.equal(closed.request_id,'close-test');assert.equal(closed.snapshot_sha256,service.snapshot_sha256);assert.equal(closed.object_id,structure().object_id);
 }finally{await service?.close();f.close();}
});
test('browser adapter calls mature APIs with the full Cartesian cell and camera-only changes',async()=>{
 const f=fixture();let service;try{
  service=await createStructureViewer({structure:structure(),assetPath:f.assetPath});const origin=service.url.split('/#')[0],script=await (await fetch(origin+'/viewer.mjs')).text(),data=await (await fetch(origin+'/api/structure',{headers:{'X-Viewer-Token':service.token}})).json(),before=JSON.stringify(data.structure),elements=new Map(),calls={};let view=[0,0,0,-10,0,0,0,1];
  const el=id=>{if(!elements.has(id))elements.set(id,{textContent:''});return elements.get(id);};
  const model={addAtoms(atoms){calls.atoms=atoms;},setCrystMatrix(matrix){calls.matrix=matrix.values;}};
  const viewer={addModel(){return model;},setStyle(a,b){calls.style=b;},addUnitCell(m,s){calls.cellModel=m;},zoomTo(){},render(){calls.renders=(calls.renders??0)+1;},getView(){return [...view];},setView(v){view=[...v];},setViewChangeCallback(fn){calls.cameraCallback=fn;},resize(){}};
  const sandbox={document:{getElementById:el},sessionStorage:{setItem(){},getItem(){return service.token;}},location:{hash:'#'+service.token,pathname:'/'},history:{replaceState(){}},window:{addEventListener(){}},fetch:async()=>({ok:true,json:async()=>data}),$3Dmol:{createViewer(){return viewer;},Matrix3:class{constructor(...values){this.values=values;}}}};
  await vm.runInNewContext('(async()=>{'+script+'})()',sandbox);assert.deepEqual(Array.from(calls.matrix),[2,.3,.2,0,3,.4,0,0,4]);assert.equal(calls.atoms.length,2);assert.equal(calls.atoms[1].elem,'Si');assert.deepEqual(Array.from(calls.atoms[1].bonds),[]);assert.match(el('viewer-status').textContent,/"state":"rendered"/);
  view=[0,0,0,-9,0,.1,0,.995];calls.cameraCallback();assert.match(el('camera-state').textContent,/camera_only/);assert.equal(JSON.stringify(data.structure),before);el('reset').onclick();assert.deepEqual(view,[0,0,0,-10,0,0,0,1]);
 }finally{await service?.close();f.close();}
});
test('renderer contact inspection counts undirected links and rejects malformed graphs or scientific-coordinate changes',()=>{
 const snapshot=validateStructureSnapshot(structure()),atoms=graphAtoms(snapshot,[[0,1]]),before=JSON.stringify(snapshot);
 assert.equal(inspectRendererContacts(atoms,snapshot),1);assert.equal(JSON.stringify(snapshot),before);
 const mutations=[a=>a[0].bonds.push(1),a=>a[1].bonds=[],a=>a[0].bonds[0]=0,a=>a[0].bonds[0]=2,a=>a[0].bondOrder[0]=2,a=>a[0].index=1,a=>a[0].x++,a=>a[0].elem='O'];
 for(const mutate of mutations){const graph=graphAtoms(snapshot,[[0,1]]);mutate(graph);assert.throws(()=>inspectRendererContacts(graph,snapshot));}
 const large=validateStructureSnapshot(manyAtoms(513));assert.throws(()=>inspectRendererContacts(graphAtoms(large,[]),large),/512/);
});
test('the exact 8192-link budget is admitted and an extra link refuses the whole graph',()=>{
 const snapshot=validateStructureSnapshot(manyAtoms(129));assert.equal(STRUCTURE_CONTACT_POLICY.undirected_contact_budget,8192);
 assert.equal(inspectRendererContacts(graphAtoms(snapshot,firstEdges(129,8192)),snapshot),8192);
 assert.throws(()=>inspectRendererContacts(graphAtoms(snapshot,firstEdges(129,8193)),snapshot),error=>error.contact_count===8193&&/整组不显示，不截断/.test(error.message));
});
test('optional contact display calls mature assignBonds once and preserves the exact camera, source snapshot and unit cell',async()=>{
 const h=await browserHarness();try{
  const before=JSON.stringify(h.data.structure),hash=h.data.snapshot_sha256,cell=JSON.stringify(h.calls.matrix),rotated=[1,2,3,-8,0,.3,0,.954];
  assert.equal(h.calls.assign,0);assert.equal(h.el('display-mode').value,'atoms');assert.equal(h.el('display-mode').disabled,false);
  h.view=rotated;h.change('contacts');let status=JSON.parse(h.el('contact-state').textContent);
  assert.equal(status.state,'ready');assert.equal(status.contact_count,1);assert.equal(status.active_contact_count,1);assert.equal(status.policy.periodic_images,false);assert.equal(status.policy.valence_constraints,false);assert.equal(status.policy.bond_order_inferred,false);assert.equal(status.policy.dft_calculation,false);assert.equal(status.policy.fallback_radius_angstrom,1.6);assert.match(status.policy.radius_policy,/missing entries.*1\.6/);
  assert.equal(h.calls.styles.at(-1).stick.singleBonds,true);assert.deepEqual(Array.from(h.view),rotated);assert.equal(h.calls.zoom,1);assert.match(h.el('contact-summary').textContent,/1 条/);
  h.change('atoms');status=JSON.parse(h.el('contact-state').textContent);assert.equal(status.active_contact_count,0);assert.equal(h.calls.styles.at(-1).stick,undefined);
  h.change('contacts');assert.equal(h.calls.assign,1);assert.deepEqual(Array.from(h.view),rotated);assert.equal(h.calls.zoom,1);
  assert.equal(JSON.stringify(h.data.structure),before);assert.equal(h.data.snapshot_sha256,hash);assert.equal(JSON.stringify(h.calls.matrix),cell);assert.equal(JSON.parse(h.el('viewer-status').textContent).scientific_coordinates_changed,false);
 }finally{await h.close();}
});
test('atom-budget refusal does not call the contact engine or truncate the atomic view',async()=>{
 const h=await browserHarness(manyAtoms(513));try{
  const before=JSON.stringify(h.data.structure),view=[0,0,0,-20,.1,0,0,.995];h.view=view;h.change('contacts');
  const status=JSON.parse(h.el('contact-state').textContent);assert.equal(status.state,'refused');assert.equal(status.active_contact_count,0);assert.match(status.reason,/512/);assert.equal(h.calls.assign,0);assert.equal(h.atoms.length,513);assert.equal(h.el('display-mode').value,'atoms');assert.deepEqual(Array.from(h.view),view);assert.equal(JSON.stringify(h.data.structure),before);assert.equal(h.calls.zoom,1);
 }finally{await h.close();}
});
test('link-budget refusal discards every renderer link and restores all atoms without resetting the camera',async()=>{
 const source=manyAtoms(129),h=await browserHarness(source,{edges:firstEdges(129,8193)});try{
  const before=JSON.stringify(h.data.structure),view=[0,0,0,-15,0,.2,0,.98];h.view=view;h.change('contacts');
  const status=JSON.parse(h.el('contact-state').textContent);assert.equal(status.state,'refused');assert.equal(status.contact_count,8193);assert.equal(status.active_contact_count,0);assert.equal(status.representation,'atoms');assert.equal(h.calls.remove,1);assert.equal(h.atoms.length,129);assert.ok(h.atoms.every(a=>a.bonds.length===0&&a.bondOrder.length===0));assert.equal(h.calls.styles.at(-1).stick,undefined);assert.deepEqual(Array.from(h.view),view);assert.equal(JSON.stringify(h.data.structure),before);assert.equal(h.calls.zoom,1);
  h.change('contacts');assert.equal(h.calls.assign,1,'The fixed rejected graph is not recomputed on every click');
 }finally{await h.close();}
});
test('an unavailable or misbehaving contact component cannot leave moved atoms or claim a successful contact view',async()=>{
 for(const options of [{missingAssign:true},{afterAssign:atoms=>{atoms[0].x=7;}}]){
  const h=await browserHarness(structure(),options);try{
   h.change('contacts');const status=JSON.parse(h.el('contact-state').textContent);assert.equal(status.state,'refused');assert.equal(status.active_contact_count,0);assert.equal(h.el('display-mode').value,'atoms');
   assert.deepEqual(h.atoms.map(a=>[a.x,a.y,a.z]),structure().positions_angstrom);assert.equal(h.calls.zoom,1);
  }finally{await h.close();}
 }
});
test('standalone owned viewer survives stdin EOF and never overwrites a connection record',async()=>{
 const f=fixture(),snapshot=path.join(f.directory,'snapshot.json'),connection=path.join(f.directory,'connection.json');writeFileSync(snapshot,JSON.stringify(structure()));let child;
 try{
  child=spawn(process.execPath,[fileURLToPath(new URL('../tools/structure_viewer.mjs',import.meta.url)),'--snapshot',snapshot,'--asset',f.assetPath,'--connection-file',connection],{stdio:['pipe','pipe','pipe'],windowsHide:true});let errors='';child.stderr.on('data',c=>{errors+=c;});
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(errors||'Viewer did not become ready')),10000);child.once('exit',code=>{clearTimeout(timer);reject(new Error('Premature viewer exit '+code+errors));});child.stdout.once('data',()=>{clearTimeout(timer);resolve();});});
  child.stdin.end();const record=JSON.parse(readFileSync(connection,'utf8'));assert.equal(record.pid,child.pid);assert.equal(record.object_id,structure().object_id);const response=await fetch('http://127.0.0.1:'+record.port+'/api/structure',{headers:{'X-Viewer-Token':record.token}});assert.equal(response.status,200);assert.equal(child.exitCode,null);assert.equal(readFileSync(snapshot,'utf8'),JSON.stringify(structure()));
  const prior=readFileSync(connection,'utf8');assert.ok(existsSync(connection));const duplicate=spawn(process.execPath,[fileURLToPath(new URL('../tools/structure_viewer.mjs',import.meta.url)),'--snapshot',snapshot,'--asset',f.assetPath,'--connection-file',connection],{stdio:'ignore',windowsHide:true});const code=await new Promise((resolve,reject)=>{duplicate.once('error',reject);duplicate.once('exit',resolve);});assert.notEqual(code,0);assert.equal(prior,readFileSync(connection,'utf8'));
 }finally{if(child&&child.exitCode===null){child.kill('SIGTERM');await new Promise(resolve=>child.once('exit',resolve));}f.close();}
});
