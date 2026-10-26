import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,readFileSync,readdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {createImagePanel} from '../tools/image_panel.mjs';

const a='a'.repeat(32),b='b'.repeat(32),c='c'.repeat(32);
const grid={domain:'spatial_pixels',source_object_id:a,source_rect_xyxy:[0,0,32,32],image_rect_xyxy:[0,0,32,32]};
const selected={kind:'rectangle',coordinate_space:'source_pixels',source_object_id:a,coordinates:[2,3,12,13],panel:grid};
async function fixture(fn){
 const workspace=mkdtempSync(path.join(tmpdir(),'dm-panel-drafts-'));let release,started;
 const entered=new Promise(r=>started=r),wait=new Promise(r=>release=r),calls=[];
 const client={async rpc(method){return method==='tools/list'?{result:{tools:['image_info','image_preview'].map(name=>({name,inputSchema:{}}))}}:{result:{}};},async tool(name,args){calls.push({name,args});if(name==='image_preview'){started();await wait;}return {data:{object_id:name==='image_preview'?b:args.object_id,kind:'view',panels:[grid],annotations:[{annotation_id:'guide',kind:'arrow',anchor:{coordinate_space:'source_pixels',source_object_id:a,coordinates:[2,2,4,4]}}],display:{gamma:1},request_id:args.request_id},png:'iVBORw0KGgo='};},async close(){}};
 const panel=await createImagePanel({workspace,python:path.resolve('python.exe'),object_id:a,client}),origin=panel.url.split('/#')[0],headers={'X-Panel-Token':panel.token,Origin:origin,'Content-Type':'application/json'};
 const post=async(endpoint,body)=>{const response=await fetch(origin+endpoint,{method:'POST',headers,body:JSON.stringify(body)});return {status:response.status,data:await response.json()};};
 const act=(action,params={},revision=panel.state().edit_state.draft_revision)=>post('/api/action',{expected_object_id:panel.state().object.object_id,draft_revision:revision,action,params});
 try{await fn({panel,post,act,entered,release,calls,origin,headers,workspace});}finally{release();await panel.close();rmSync(workspace,{recursive:true,force:true});}
}
test('a new draft is accepted while a real server write waits; late result cannot switch the visible base',async()=>fixture(async({panel,act,entered,release,calls})=>{
 const waiting=act('preview',{gamma:2},0);await entered;
 const draft=await act('draft',{draft_revision:1,dirty:true,gesture_active:false,selection:selected});
 assert.equal(draft.status,200);assert.equal(panel.state().object.object_id,a);release();
 const response=await waiting;assert.equal(response.status,200);assert.equal(response.data.object.object_id,a);assert.equal(response.data.pending_result.object_id,b);assert.deepEqual(response.data.edit_state.selection,selected);
 assert.equal(calls.filter(c=>c.name==='image_preview').length,1);
 assert.equal((await act('accept-result')).status,409);
 await act('draft',{draft_revision:2,dirty:false,gesture_active:false});
 assert.equal((await act('accept-result')).data.object.object_id,b);
}));
test('Agent presentation queues on dirty or active gesture; original receipt survives another HTTP client and refuses conflicts',async()=>fixture(async({panel,act,post,origin,headers,workspace})=>{
 await act('draft',{draft_revision:1,dirty:true,gesture_active:true,selection:selected});
 const body={object_id:c,expected_object_id:a,draft_revision:1,request_id:'known-before-show'};
 const result=await post('/api/present',body);assert.equal(result.status,200);assert.equal(result.data.presentation.status,'queued');assert.equal(result.data.object.object_id,a);
 const queried=await (await fetch(origin+'/api/present?request_id=known-before-show',{headers})).json();assert.deepEqual(queried,result.data);
 assert.equal((await post('/api/present',{...body,object_id:b})).status,409);
 assert.equal((await post('/api/present',body)).data.presentation.status,'queued');
 assert.equal(readdirSync(path.join(panel.journal,'presentations')).filter(f=>f.endsWith('.request.json')).length,1);
 const probe=await (await fetch(origin+'/api/revision',{headers})).json();assert.equal(probe.pending_result.object_id,c);assert.equal(probe.png_base64,undefined);
 const saved=JSON.parse(readFileSync(path.join(panel.journal,'current-selection.json')));assert.equal(saved.object_id,a);assert.equal(saved.pending_result.object_id,c);
}));
test('draft schema, wrong base, decreasing revision and foreign origin cannot change the shared selection',async()=>fixture(async({panel,act,post,origin,headers,calls})=>{
 await act('draft',{draft_revision:7,dirty:true,gesture_active:false,selection:selected});
 for(const params of [{draft_revision:6,dirty:false,gesture_active:false},{draft_revision:8,dirty:0,gesture_active:false},{draft_revision:8,dirty:false,gesture_active:false,selection:{...selected,source_object_id:c}}])assert.ok((await act('draft',params)).status>=400);
 assert.equal((await post('/api/action',{expected_object_id:c,action:'draft',params:{draft_revision:8,dirty:false,gesture_active:false}})).status,409);
 assert.equal((await fetch(origin+'/api/revision',{headers:{...headers,Origin:'https://foreign.invalid'}})).status,403);
 assert.equal(panel.state().edit_state.draft_revision,7);assert.deepEqual(panel.state().selection,selected);assert.equal(calls.length,1);
}));
test('annotation drafts expose their saved scientific anchor but cannot change identity or escape bounds',async()=>fixture(async({panel,act,calls})=>{
 const annotation_edit={annotation_id:'guide',coordinates:[3,3,5,5],text:'candidate',color:'cyan',status:'hypothesized'};
 let response=await act('draft',{draft_revision:1,dirty:true,gesture_active:false,annotation_edit});assert.equal(response.status,200);
 assert.equal(response.data.edit_state.annotation_edit.source_object_id,a);assert.equal(response.data.edit_state.annotation_edit.coordinate_space,'source_pixels');assert.deepEqual(response.data.edit_state.annotation_edit.coordinates,[3,3,5,5]);
 for(const edit of [{...annotation_edit,annotation_id:'missing'},{...annotation_edit,source_object_id:c},{...annotation_edit,coordinates:[0,0,200,200]},{...annotation_edit,color:'untrusted'}])assert.ok((await act('draft',{draft_revision:2,dirty:true,gesture_active:false,annotation_edit:edit})).status>=400);
 response=await act('draft',{draft_revision:2,dirty:false,gesture_active:false,annotation_edit:null});assert.equal(response.data.edit_state.annotation_edit,null);assert.equal(calls.length,1);
}));
