// Focused read-only presentation/export contracts; not browser acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import {MeasurementWorkspace,measurementValues,measurementType,measurementNumber,measurementDetails,inspectorDetails,tabularCell,exportMeasurementTable} from '../ui/image-panel/measurement-workspace.mjs';
const A='a'.repeat(32),B='b'.repeat(32),C='c'.repeat(32);
function result(overrides={}){return {object_id:A,kind:'measure',parent_object_id:B,request_id:'test-measure',points:[[0,0],[.125,-.25]],coordinate_space:'frequency_cycles_per_pixel',dc_reference_point_index:0,physical_frequency_magnitude:5,physical_frequency_unit:'1/nm',period:.2,period_unit:'nm',d_spacing:.2,d_spacing_unit:'nm',frequency_distance_cycles_per_pixel:Math.hypot(.125,.25),status:'current',annotation_id:'g1',source:{frame_index:9,source_rect_xyxy:[20,30,84,94]},...overrides};}
test('DC-reflection period and an arbitrary two-peak difference stay distinct',()=>{
 const dc=result(),difference=result({points:[[.1,.2],[.3,.4]],dc_reference_point_index:null,d_spacing:null,d_spacing_unit:null});
 assert.equal(measurementType(dc),'DC→峰');assert.equal(measurementType(difference),'两点差矢量');
 assert.equal(measurementValues(dc).find(v=>v.kind==='d_spacing').value,.2);
 assert.equal(measurementValues(difference).find(v=>v.kind==='period').label,'差矢量周期');
 assert.ok(!measurementValues(difference).some(v=>v.kind==='d_spacing'));
});
test('uncalibrated measurements retain pixel frequencies and never invent physical units',()=>{
 const m=result({physical_frequency_magnitude:null,physical_frequency_unit:null,period:null,period_unit:null,d_spacing:null,d_spacing_unit:null});
 assert.deepEqual(measurementValues(m),[{kind:'pixel_frequency',label:'频率差',value:Math.hypot(.125,.25),unit:'cycles/pixel'}]);
 assert.equal(measurementNumber(null),'未知');assert.equal(measurementNumber(NaN),'未知');
 const detail=inspectorDetails({object_id:A,shape_yx:[96,128],dtype:'uint16',source_identity:{path:'synthetic.tiff'},frame_index:0,domain:'spatial_pixels',user_context:{data_meaning:'synthetic_demo'}});
 assert.match(detail.find(([key])=>key==='科学数组')[1],/96 × 128.*uint16/);
 assert.match(detail.find(([key])=>key==='来源')[1],/合成/);
 assert.match(detail.find(([key])=>key==='XY 标定')[1],/未知/);
});
test('CSV/TSV protect text formula fields while keeping numeric fields usable and unknowns empty',()=>{
 assert.equal(tabularCell(-.125),'-0.125');assert.equal(tabularCell('  =SUM(1,2)'),"\"'  =SUM(1,2)\"");assert.equal(tabularCell('@cmd'),"'@cmd");
 assert.equal(tabularCell(Infinity),'');assert.equal(tabularCell(null),'');
 const table=exportMeasurementTable([result({name:'=2+2',status:'needs_remeasurement',xy_calibration:{calibration_id:C,revision:2,source_text:'@user-provided'}})]);
 assert.match(table,/^name,type,status,/);assert.match(table,/\r\n'=2\+2,DC→峰,待重测,/);assert.match(table,/,0.125,-0.25,/);assert.match(table,/'@user-provided/);
 assert.match(exportMeasurementTable([result()],{delimiter:'\t'}),/^name\ttype\tstatus/);
 assert.throws(()=>exportMeasurementTable([],{delimiter:';'}),/CSV and TSV/);
});
test('details expose immutable points, original references and saved calibration version',()=>{
 const m=result({xy_calibration:{calibration_id:C,revision:3,source:'user_statement',source_text:'independent synthetic grid'}});
 const details=Object.fromEntries(measurementDetails(m));assert.equal(details['科学端点'],'[[0,0],[0.125,-0.25]]');assert.equal(details['源帧'],'10');assert.match(details['标定版本'],/v3/);assert.equal(details['原始结果'],A);
});
test('late results cannot replace another frame/object or a newer revision and reads never call operations',async()=>{
 let state={object:{object_id:A},state_revision:1},release;const calls=[];
 const workspace=new MeasurementWorkspace({document:null,getState:()=>state,api:url=>{calls.push(url);return new Promise(resolve=>release=resolve);}});
 const waiting=workspace.refresh();state={object:{object_id:B},state_revision:2};release({current:{object_id:A},entries:[result()]});assert.equal(await waiting,false);assert.deepEqual(workspace.entries,[]);
 const waiting2=workspace.refresh();state={object:{object_id:B},state_revision:3};release({current:{object_id:B},entries:[result()]});assert.equal(await waiting2,false);
 const waiting3=workspace.refresh();release({current:{object_id:B},entries:[result(),result({object_id:C,annotation_id:'g2'})]});assert.equal(await waiting3,true);assert.equal(workspace.entries.length,2);
 const preserved=JSON.stringify(workspace.entries);assert.equal(workspace.selectAnnotation('g1'),true);assert.equal(workspace.selectedId,A);assert.equal(workspace.hasAnnotation('missing'),false);assert.equal(JSON.stringify(workspace.entries),preserved);assert.ok(calls.every(url=>url.startsWith('/api/measurements?object_id=')));
});
test('newer overlapping read wins, and canvas/table selection does not recompute',async()=>{
 let releaseFirst,releaseSecond,number=0;const selected=[];
 const workspace=new MeasurementWorkspace({document:null,getState:()=>({object:{object_id:A},state_revision:5}),onSelect:e=>selected.push(e.object_id),api:()=>new Promise(resolve=>{if(++number===1)releaseFirst=resolve;else releaseSecond=resolve;})});
 const one=workspace.refresh(),two=workspace.refresh();releaseSecond({current:{object_id:A},entries:[result({object_id:B})]});assert.equal(await two,true);releaseFirst({current:{object_id:A},entries:[result({object_id:C})]});assert.equal(await one,false);assert.equal(workspace.entries[0].object_id,B);
 workspace.select(B);assert.deepEqual(selected,[B]);assert.equal(number,2);
});
