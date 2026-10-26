// Declarative control-plane contracts. These describe existing enforcement;
// they do not authorize host calls or replace any adapter's scientific guards.
export function nativeContract(d){
  const n=d.name,query=n==='dm_native_result',optional=!d.inputSchema.required.includes('request_id');
  const readonly=['dm_status','dm_datasets','dm_native_mean','dm_native_summary','dm_native_preview','dm_native_read','dm_native_rois','dm_native_result_info'].includes(n);
  const input=n==='dm_native_binary'?['NativeImageRef(left/right explicit same-session IDs)']:n==='dm_native_import'?['ScientificArrayRef(finite 2D float32 NPY)','SourceManifestRef','CalibrationRevisionRef(raw signed axes)']:n==='dm_native_result'?['OriginalRequestRef(same native session)']:d.inputSchema.properties.image_id?['NativeImageRef(explicit ID; supported dtype/domain only)']:[];
  if(n==='dm_native_profile')input.push('GUISelectionRef(exact document/display/ROI and expected integer line)');
  if(['dm_native_release','dm_native_result_info'].includes(n))input.push('RetentionTokenRef(from original creation receipt)');
  const outputs=n==='dm_native_read'?['ScientificArraySnapshot(dtype-preserving bounded ROI)','NativeCalibrationSnapshot']:n==='dm_native_preview'?['ImageViewRef(display PNG only)']:n==='dm_native_show'?['DMDocumentRef(delivery only; visibility/model observation unknown)']:n==='dm_native_result'?['OriginalResultSnapshot']:n==='dm_native_rois'?['GUISelectionSnapshot(non-atomic; explicit IDs)']:['dm_native_release','dm_native_result_info'].includes(n)?['RetentionSnapshot']:readonly?['NativeObservationSnapshot']:['NativeImageRef(new retained scientific result)'];
  return {backend:'dm-native',inputs:input,outputs:[...outputs,'OperationReceipt(NB2)'],
    effects:{kind:query?'query-original':readonly?'read-host':n==='dm_native_release'?'release-plugin-reference':n==='dm_native_show'?'create-or-reuse-document':n==='dm_native_import'?'stage-handoff-and-create-host-image':'create-retained-host-image',sourceMutation:false,requestId:query?'query':optional?'optional':'required'},
    gates:query?['NB2:same-session-original-request']:['NB2:session-and-receipt-identity',...(['dm_status','dm_datasets'].includes(n)?[]:['host:exact-profile-and-per-operation-dtype-domain-qualification']), 'authority:existing-native-adapter; never inferred from registration'],
    execution:{resourceKeys:['dm-native:session'],serialization:'Existing NativeBridge/host dispatch; no new queue or concurrent vendor calls',budgets:[d.description,'NB2 transport and native result-pool bounds remain authoritative'],cancellation:'Stop waiting only; submitted host operation may complete; never auto-resubmit'},
    recovery:{method:'query-original-id-only',tool:'dm_native_result',idField:'request_id',scope:'Same still-queryable native session only; STOP/exit/restart recovery not promised'}};
}
export function pythonContract(d){
  const n=d.name,local=['dm_2d_preview','dm_2d_analyze','dm_2d_result'].includes(n);
  const fileWrite=['dm_export','dm_spectrum_export','dm_2d_capture','dm_2d_preview','dm_2d_analyze'].includes(n);
  const hostCreate=['dm_open','dm_crop','dm_4dstem_virtual'].includes(n);
  const arbitrary=n==='dm_run_script',query=n==='dm_2d_result';
  const inputs=local?['CaptureRef(explicit immutable capture/result directory)']:n==='dm_open'?['ScientificFileRef(explicit path)']:n.startsWith('dm_4dstem_')?['Bounded4DSourceRef(explicit axes/index/bounds)']:d.inputSchema.properties.image_id?['DMImageRef(legacy explicit ID or front where schema permits)']:[];
  return {backend:local?'external-analysis-worker':'dm-python',inputs,
    outputs:query?['OriginalAnalysisStatusOrResult']:local?['ImageViewRef or AnalysisResultRef(display/scientific roles preserved)']:n==='dm_2d_capture'?['ScientificArrayRef(fixed capture)','NativeCalibrationSnapshot']:hostCreate?['DMImageRef(new result)']:fileWrite?['ExportRef(new file only)']:['DMObservationOrResult'],
    effects:{kind:arbitrary?'explicit-arbitrary-script':query?'query-result':fileWrite?'write-new-files':hostCreate?'create-host-image':n==='dm_4dstem_open'?'create-session-index':'read-host',sourceMutation:arbitrary,requestId:'none'},
    gates:[arbitrary?'env:DM_MCP_ALLOW_DMSCRIPT=1':local?'independent-analysis-runtime':'explicit-python-loopback-host','authority:existing-default-adapter; no native fallback',...(n.startsWith('dm_spectrum')?['explicit-energy-axis; real-spectroscopy-NOT_TESTED']:[])],
    execution:{resourceKeys:[local?'analysis-worker:process':'dm-python:loopback'],serialization:local?'Existing independent analysis process lifecycle':'Existing Bridge queue/deadline; no new host concurrency',budgets:[d.description,local?'Existing payload/output/PNG and hard worker deadline bounds':'Existing loopback frame and per-call deadline bounds'],cancellation:local?'Existing worker-specific stop-wait/hard-deadline policy retained':'Stop waiting; sent operation may still run; no automatic resend'},
    recovery:local?{method:'inspect-existing-output-only',tool:'dm_2d_result',idField:n==='dm_2d_analyze'?'operation_id':null,scope:'Existing capture/result directory contract, not a new request-ID journal'}:{method:'inspect-host-no-automatic-retry',tool:null,idField:null,scope:'Legacy Python bridge has no native-style durable original-request QUERY guarantee'}};
}
