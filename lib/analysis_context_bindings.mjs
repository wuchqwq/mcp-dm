// Transitional scientific-provider boundary. The portable context imports none
// of this code: existing workers validate immutable science, this port binds refs.
import {createHash} from 'node:crypto';
import {readFileSync,realpathSync,statSync} from 'node:fs';
import path from 'node:path';

const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
const same=(a,b)=>canonical(a??null)===canonical(b??null);
export const sameScientificGrid=(a,b)=>!!a&&!!b&&same(a,b);
const requireMatch=(ok,message)=>{if(!ok)throw Object.assign(new Error(message),{code:'SCIENTIFIC_BINDING_MISMATCH'});};
const rows=value=>value===null||value===undefined?[]:Array.isArray(value)?value:[value];
const active=value=>rows(value).filter(entry=>entry.status==='active');
const recordDependency=record=>record?Object.fromEntries(['calibration_id','revision','status','source','coordinate_domain','centre_revision_id'].filter(key=>record[key]!==undefined).map(key=>[key,record[key]])):null;

export function createScientificContextBindings({providers,signal}={}) {
  const cache=new Map();
  const workspaceFor=ref=>{
    const workspace=Object.values(providers).find(value=>value.requestScope?.provider===ref.provider);
    requireMatch(workspace&&['provider','workspace','session'].every(key=>workspace.requestScope[key]===ref[key]),'Reference does not belong to a configured provider/workspace/session');
    return workspace;
  };
  async function metadata(ref) {
    const key=canonical(ref);if(cache.has(key))return cache.get(key);
    const pending=(async()=>{
      requireMatch(/^[a-f0-9]{32}$/.test(ref.objectId),'A committed immutable scientific object ID is required');
      const workspace=workspaceFor(ref),name=ref.provider==='external-image-workspace'?'image_info':'structure_info';
      const response=await workspace.call(name,{object_id:ref.objectId},signal);
      requireMatch(response&&!response.isError,'Provider refused scientific reference validation');
      const value=JSON.parse(response.content.find(part=>part.type==='text').text);
      requireMatch(value.object_id===ref.objectId&&value.backend===ref.provider,'Provider returned a different object/backend identity');
      const root=realpathSync.native(workspace.workspace),file=realpathSync.native(value.manifest_path),relative=path.relative(root,file);
      requireMatch(relative&&!relative.startsWith('..')&&!path.isAbsolute(relative)&&statSync(file).size<=2*1024*1024,'Scientific manifest escapes configured workspace or budget');
      const bytes=readFileSync(file),saved=JSON.parse(bytes.toString('utf8'));
      requireMatch(saved.object_id===value.object_id&&saved.backend===value.backend,'Manifest and provider identity disagree');
      requireMatch(Object.entries(saved).every(([key,item])=>same(item,value[key])),'Scientific manifest changed after provider validation');
      return {value,manifestHash:createHash('sha256').update(bytes).digest('hex'),manifestPath:file};
    })();cache.set(key,pending);return pending;
  }
  const relative=(ref,objectId)=>({...ref,objectId});
  async function imageProof(ref,top) {
    let current=top.value,record=current.xy_calibration,visited=new Set(),lineage=[];
    while(['calibration','context','measure','annotate'].includes(current.kind)) {
      requireMatch(!visited.has(current.object_id)&&visited.size<32,'Scientific reference ancestry is cyclic or exceeds budget');
      visited.add(current.object_id);lineage.push(current.object_id);
      const parent=current.kind==='annotate'?current.render_base_object_id:current.kind==='measure'?current.parent_object_id:current.base_object_id;
      current=(await metadata(relative(ref,parent))).value;record=record??current.xy_calibration;
    }
    lineage.push(current.object_id);
    const spectral=['fft','fft_view'].includes(current.kind),roles=[];
    if(['frame','view'].includes(current.kind))roles.push('experiment');
    if(spectral)roles.push('fft');
    if(top.value.image_path)roles.push('display');
    if(record)roles.push('calibration');
    if(record?.centre_revision_id||record?.dc_index_xy)roles.push('center');
    if(top.value.kind==='measure')roles.push('points','measurements');
    let grid=top.value.scientific_grid_identity??null;
    if(!grid&&current.shape_yx&&current.files_sha256?.['data.npy']) {
      const panel=current.panels?.[0];
      grid={source_grid_object_id:spectral?(current.spectrum_object_id??current.object_id):(current.kind==='view'?panel?.source_object_id:current.object_id),
        shape_yx:current.shape_yx,dtype:current.dtype,array_sha256:current.files_sha256['data.npy'],
        source_rect_xyxy:spectral?null:(current.kind==='view'?panel?.source_rect_xyxy:[0,0,current.shape_yx[1],current.shape_yx[0]]),
        coordinate_space:spectral?'frequency_cycles_per_pixel':['frequency','reciprocal'].includes(current.array_domain)?'source_array_indices':'source_pixels'};
    }
    // Lineage is metadata only. No pixels, inferred calibration or new FFT.
    let ancestor=current;
    for(let count=0;ancestor.parent_object_id&&count<32;count++) {
      const parent=(await metadata(relative(ref,ancestor.parent_object_id))).value;
      requireMatch(!lineage.includes(parent.object_id),'Scientific source ancestry is cyclic');
      lineage.push(parent.object_id);ancestor=parent;
      if(ancestor.base_object_id){ancestor=(await metadata(relative(ref,ancestor.base_object_id))).value;lineage.push(ancestor.object_id);}
    }
    return {manifestHash:top.manifestHash,kind:top.value.kind,roles,
      scientific:{grid,lineageIds:lineage,manifestPath:top.manifestPath,
        calibration:top.value.calibration_dependency??recordDependency(record),xyScale:record?.xy_scale??null,
        centerXY:record?.dc_index_xy??null,points:top.value.points??null,coordinateSpace:top.value.coordinate_space??grid?.coordinate_space??null}};
  }
  async function resolveReference(ref) {
    const top=await metadata(ref);
    if(ref.provider==='external-image-workspace')return imageProof(ref,top);
    const value=top.value,roles={structure:['reference'],orient:['orientation'],simulate:['simulation'],register:['registration'],compare:['comparison']}[value.kind]??[];
    return {manifestHash:top.manifestHash,kind:value.kind,roles,scientific:{manifestPath:top.manifestPath,
      structureId:value.structure_object_id??(value.kind==='structure'?value.object_id:null),
      orientationId:value.parameters?.orientation_id??value.orientation?.orientation_id??null,
      simulationId:value.simulation_object_id??(value.kind==='simulate'?value.object_id:null),
      measurementPaths:(value.parameters?.measurement_paths??[]).map(filename=>path.resolve(filename)),
      registrationId:value.registration_object_id??value.registration?.proposal_object_id??null,
      grid:value.analysis_binding?.scientific_grid_identity??null,
      calibration:value.analysis_binding?.calibration_dependency??null}};
  }
  async function validateBindings({slot,entry,slots}) {
    const science=entry.proof.scientific;
    if(entry.ref.provider==='external-image-workspace') {
      const parent=entry.dependsOn.fft?active(slots.fft)[0]:entry.dependsOn.experiment?active(slots.experiment)[0]:null;
      if(slot==='fft'&&active(slots.experiment).length)requireMatch(science.lineageIds.includes(slots.experiment.ref.objectId),'FFT was not produced from the selected experiment; dependency hashes cannot relabel its source');
      if(parent&&slot!=='fft')requireMatch(same(science.grid,parent.proof.scientific.grid),'Image reference uses a different scientific source/frame/ROI/FFT grid');
      const calibration=active(slots.calibration)[0],center=active(slots.center)[0];
      if(['calibration','center'].includes(slot)&&calibration&&center)requireMatch(same(calibration.proof.scientific.calibration,center.proof.scientific.calibration),'Selected calibration and centre belong to different geometry revisions');
      if(['measurements','display'].includes(slot)&&calibration)requireMatch(same(science.calibration,calibration.proof.scientific.calibration),'Saved result uses a different calibration revision; remeasure or render the selected wrapper');
      if(['measurements','display'].includes(slot)&&center)requireMatch(same(science.calibration,center.proof.scientific.calibration),'Saved result uses a different centre revision');
      if(slot==='measurements'&&active(slots.points).length)requireMatch(active(slots.points).some(point=>same(point.proof.scientific.grid,science.grid)&&same(point.proof.scientific.points,science.points)&&point.proof.scientific.coordinateSpace===science.coordinateSpace),'Saved measurement does not use the selected point anchors');
    } else {
      const reference=active(slots.reference)[0],orientation=active(slots.orientation)[0],simulation=active(slots.simulation)[0];
      if(reference&&['orientation','simulation'].includes(slot))requireMatch(science.structureId===reference.ref.objectId,'Structure result belongs to a different immutable reference structure');
      if(orientation&&slot==='simulation')requireMatch(science.orientationId===orientation.ref.objectId,'Simulation used a different scientific orientation');
      if(['registration','comparison'].includes(slot)) {
        if(simulation)requireMatch(science.simulationId===simulation.ref.objectId,'Comparison uses a different saved simulation');
        const measurements=active(slots.measurements);
        if(measurements.length)requireMatch(same(science.measurementPaths,measurements.map(measure=>path.resolve(measure.proof.scientific.manifestPath))),'Registration/comparison was computed with different committed measurements');
        const parent=active(slots.fft)[0]??active(slots.experiment)[0],calibration=active(slots.calibration)[0]??active(slots.center)[0];
        if(parent)requireMatch(same(science.grid,parent.proof.scientific.grid),'Comparison uses a different current scientific grid');
        if(calibration)requireMatch(same(science.calibration,calibration.proof.scientific.calibration),'Comparison uses an obsolete scale or centre');
        if(slot==='comparison'&&active(slots.registration).length)requireMatch(science.registrationId===slots.registration.ref.objectId,'Comparison did not use the selected constrained registration');
      }
    }
  }
  return {resolveReference,validateBindings};
}
