import test from 'node:test';
import assert from 'node:assert/strict';
import {constrainSelectionDrag,selectionFromDrag,selectionRectangle,transformCoordinates} from '../ui/image-panel/coordinates.mjs';

const spatial={domain:'spatial_pixels',source_object_id:'a'.repeat(32),source_rect_xyxy:[20,12,220,112],image_rect_xyxy:[0,0,100,100]};
function selected(panel,start,end,kind){const constrained=constrainSelectionDrag(panel,start,end,{kind,constrained:true});return selectionFromDrag([panel],constrained.start,constrained.end,{kind});}

test('square ROI uses source-pixel edges under anisotropic display mapping and stays square at boundaries',()=>{
 const square=selected(spatial,[10.2,10.3],[40,20],'rectangle');
 assert.deepEqual(square.coordinates,[40,22,100,82]);assert.deepEqual(selectionRectangle(square),[40,22,100,82]);
 assert.notEqual(transformCoordinates(square.coordinates,spatial,{edges:true,inverse:true})[2]-10,60);
 for(const end of [[500,500],[-500,-500],[500,-500],[-500,500]]){
  const rect=selectionRectangle(selected(spatial,[50,50],end,'rectangle'));
  assert.equal(rect[2]-rect[0],rect[3]-rect[1]);assert.ok(rect[0]>=20&&rect[1]>=12&&rect[2]<=220&&rect[3]<=112);
 }
});

test('FFT ROI square means equal original bin counts, including odd grids and cropped views',()=>{
 const panel={domain:'frequency',source_object_id:'b'.repeat(32),fft_shape_yx:[55,95],fft_rect_xyxy:[38,22,58,34],image_rect_xyxy:[60,20,260,140]};
 const rect=selectionRectangle(selected(panel,[90,40],[240,70],'rectangle'));
 assert.deepEqual(rect,[41,24,51,34]);assert.equal(rect[2]-rect[0],rect[3]-rect[1]);
});

test('line and arrow choose the nearest source-grid axis and retain it when the pointer exits the panel',()=>{
 for(const kind of ['line','arrow']){
  const horizontal=selected(spatial,[10,10],[30,40],kind).coordinates;
  assert.equal(horizontal[1],horizontal[3]);assert.notEqual(horizontal[0],horizontal[2]);
  const vertical=selected(spatial,[10,10],[12,500],kind).coordinates;
  assert.equal(vertical[0],vertical[2]);assert.ok(vertical[3]<=111);
 }
 const unconstrained=constrainSelectionDrag(spatial,[10,10],[30,40],{kind:'line'});assert.deepEqual(unconstrained,{start:[10,10],end:[30,40]});
});
