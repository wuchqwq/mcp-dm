// Hand-solvable camera relationships; scientific coordinates are never edited.
import test from 'node:test';
import assert from 'node:assert/strict';
import {relatedViewport} from '../ui/image-panel/viewer-state.mjs';
import {transformCoordinates} from '../ui/image-panel/coordinates.mjs';

const clone=value=>JSON.parse(JSON.stringify(value));
const panel={domain:'spatial_pixels',source_object_id:'a'.repeat(32),source_rect_xyxy:[20,12,220,112],image_rect_xyxy:[0,0,400,200]};
const initial={object:{object_id:'b'.repeat(32),scientific_grid_identity:{array_sha256:'original-array',source_rect_xyxy:[20,12,220,112]},panels:[panel]},frame_identity:{frame_object_id:'f'.repeat(32)}};
const camera={scale:2,x:-100,y:30},viewport=[800,600];
const near=(actual,expected)=>{for(const key of ['scale','x','y'])assert.ok(Math.abs(actual[key]-expected[key])<1e-9,`${key}: ${actual[key]} versus ${expected[key]}`);};

test('new annotation or display object ID on the same scientific grid preserves the camera',()=>{
 const next=clone(initial);next.object.object_id='c'.repeat(32);next.object.kind='annotate';
 near(relatedViewport(camera,initial,next,viewport),camera);
 const display=clone(next);display.object.object_id='d'.repeat(32);display.object.display={gamma:1.7};
 near(relatedViewport(camera,next,display,viewport),camera);
});

test('panning the image away from centre survives same-region revisions and inspector viewport resizing',()=>{
 const offImageCamera={scale:1.4,x:500,y:400},next=clone(initial);next.object.object_id='c'.repeat(32);
 // Both the full and inspector-reduced viewport centres lie outside the image.
 // Opening properties must not reset an intentional off-centre scientific view.
 for(const size of [[800,600],[496,600]]){
  const renderedCentre=[(size[0]/2-offImageCamera.x)/offImageCamera.scale,(size[1]/2-offImageCamera.y)/offImageCamera.scale];
  assert.ok(renderedCentre[0]<0&&renderedCentre[1]<0);
  near(relatedViewport(offImageCamera,initial,next,size),offImageCamera);
 }
});

test('same scientific grid rendered at another pixel size rebases around the same source coordinate',()=>{
 const next=clone(initial);next.object.object_id='c'.repeat(32);next.object.panels[0].image_rect_xyxy=[0,0,200,100];
 const rebased=relatedViewport(camera,initial,next,viewport);
 // Old rendered centre=(250,135); source=(144.75,79.25).
 // New rendered centre=(124.75,67.25), so scale4 and offsets(-99,31).
 near(rebased,{scale:4,x:-99,y:31});
 const centre=viewport.map(v=>v/2);
 const sourceBefore=transformCoordinates([(centre[0]-camera.x)/camera.scale,(centre[1]-camera.y)/camera.scale],panel);
 const sourceAfter=transformCoordinates([(centre[0]-rebased.x)/rebased.scale,(centre[1]-rebased.y)/rebased.scale],next.object.panels[0]);
 assert.deepEqual(sourceAfter,sourceBefore);
});

test('a view crop uses the actual source-to-render relationship rather than reusing old pixel offsets',()=>{
 const next=clone(initial);next.object.panels[0].source_rect_xyxy=[70,37,170,87];next.object.panels[0].image_rect_xyxy=[0,0,400,200];
 const rebased=relatedViewport(camera,initial,next,viewport);
 assert.notDeepEqual(rebased,camera);
 const centre=viewport.map(v=>v/2),sourceBefore=transformCoordinates([(centre[0]-camera.x)/camera.scale,(centre[1]-camera.y)/camera.scale],panel);
 const sourceAfter=transformCoordinates([(centre[0]-rebased.x)/rebased.scale,(centre[1]-rebased.y)/rebased.scale],next.object.panels[0]);
 for(let axis=0;axis<2;axis++)assert.ok(Math.abs(sourceAfter[axis]-sourceBefore[axis])<1e-10);
});

test('changed scientific ROI, frame, FFT producer or anisotropic mapping refuses blind camera reuse',()=>{
 const mutations=[
  next=>{next.object.scientific_grid_identity.source_rect_xyxy=[0,0,100,100];},
  next=>{next.frame_identity.frame_object_id='e'.repeat(32);},
  next=>{next.object.panels[0].source_object_id='e'.repeat(32);},
  next=>{next.object.panels[0].domain='frequency';next.object.panels[0].fft_shape_yx=[128,128];},
  next=>{next.object.panels[0].image_rect_xyxy=[0,0,200,200];}
 ];
 for(const mutate of mutations){const next=clone(initial);mutate(next);assert.equal(relatedViewport(camera,initial,next,viewport),null);}
});

test('duplicate-source comparison panels have no unique correspondence and are refused',()=>{
 const next=clone(initial);next.object.panels.push({...clone(panel),image_rect_xyxy:[420,0,820,200]});
 assert.equal(relatedViewport(camera,initial,next,viewport),null);
});
