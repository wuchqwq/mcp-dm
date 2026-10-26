import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync,existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import vm from 'node:vm';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {createStructureViewer,validateStructureSnapshot,read3DmolAsset,STRUCTURE_VIEWER_VERSION} from '../tools/structure_viewer.mjs';
const structure=()=>({object_id:'a'.repeat(32),symbols:['C','Si'],positions_angstrom:[[0,0,0],[1.1,-.3,.7]],cell_angstrom:[[2,0,0],[.3,3,0],[.2,.4,4]],pbc:[true,true,true]});
function fixture(){
 const directory=mkdtempSync(path.join(tmpdir(),'mcp-structure-viewer-')),packageDirectory=path.join(directory,'node_modules','3dmol'),assetPath=path.join(packageDirectory,'build','3Dmol-min.js');mkdirSync(path.dirname(assetPath),{recursive:true});
 // This is a transport fixture, not a WebGL or real 3Dmol qualification.
 writeFileSync(assetPath,'/* offline transport fixture; not a rendered viewer */');writeFileSync(path.join(packageDirectory,'package.json'),JSON.stringify({name:'3dmol',version:STRUCTURE_VIEWER_VERSION,license:'BSD-3-Clause'}));writeFileSync(path.join(packageDirectory,'LICENSE'),'BSD-3-Clause fixture license');
 return {directory,packageDirectory,assetPath,close(){rmSync(directory,{recursive:true,force:true});}};
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
 const s=structure();s.cell_angstrom=Array.from({length:3},()=>[0,0,0]);s.pbc=[false,false,false];assert.equal(validateStructureSnapshot(s).cell_drawn,false);s.pbc[0]=true;assert.throws(()=>validateStructureSnapshot(s),/full-rank/);
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
  const page=await (await fetch(origin+'/')).text();assert.ok(!page.includes(structure().object_id));assert.ok(!page.includes('positions_angstrom'));assert.match(page,/3Dmol-min\.js/);assert.match(response.headers.get('content-security-policy'),/connect-src 'self'/);
  assert.equal((await fetch(origin+'/3Dmol-min.js')).status,200);assert.equal((await fetch(origin+'/LICENSE-3Dmol.txt')).status,200);
 }finally{await viewer?.close();f.close();}
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
test('standalone owned viewer survives stdin EOF and never overwrites a connection record',async()=>{
 const f=fixture(),snapshot=path.join(f.directory,'snapshot.json'),connection=path.join(f.directory,'connection.json');writeFileSync(snapshot,JSON.stringify(structure()));let child;
 try{
  child=spawn(process.execPath,[fileURLToPath(new URL('../tools/structure_viewer.mjs',import.meta.url)),'--snapshot',snapshot,'--asset',f.assetPath,'--connection-file',connection],{stdio:['pipe','pipe','pipe'],windowsHide:true});let errors='';child.stderr.on('data',c=>{errors+=c;});
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(errors||'Viewer did not become ready')),10000);child.once('exit',code=>{clearTimeout(timer);reject(new Error('Premature viewer exit '+code+errors));});child.stdout.once('data',()=>{clearTimeout(timer);resolve();});});
  child.stdin.end();const record=JSON.parse(readFileSync(connection,'utf8'));assert.equal(record.pid,child.pid);assert.equal(record.object_id,structure().object_id);const response=await fetch('http://127.0.0.1:'+record.port+'/api/structure',{headers:{'X-Viewer-Token':record.token}});assert.equal(response.status,200);assert.equal(child.exitCode,null);assert.equal(readFileSync(snapshot,'utf8'),JSON.stringify(structure()));
  const prior=readFileSync(connection,'utf8');assert.ok(existsSync(connection));const duplicate=spawn(process.execPath,[fileURLToPath(new URL('../tools/structure_viewer.mjs',import.meta.url)),'--snapshot',snapshot,'--asset',f.assetPath,'--connection-file',connection],{stdio:'ignore',windowsHide:true});const code=await new Promise((resolve,reject)=>{duplicate.once('error',reject);duplicate.once('exit',resolve);});assert.notEqual(code,0);assert.equal(prior,readFileSync(connection,'utf8'));
 }finally{if(child&&child.exitCode===null){child.kill('SIGTERM');await new Promise(resolve=>child.once('exit',resolve));}f.close();}
});
