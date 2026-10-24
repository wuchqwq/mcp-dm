from pathlib import Path
root=Path.cwd()
p=root/'tools/native_region_handoff.mjs';s=p.read_text()
s=s.replace('export function planRegion({imageId,rect,blockSamples=LIMIT.samplesPerBlock,session,hostPid,requestId}) {','function regionLayout({imageId,rect,blockSamples=LIMIT.samplesPerBlock,session,hostPid,requestId}) {',1)
a="""  const prefix='region-'+hash(canonical({imageId,rect,blockSamples,session,hostPid,requestId})).slice(0,32);"""
b="""  return {width,height,tileWidth,tileHeight};
}

// A null namespace exists only to validate completed historical journals.
// It must never be used for a new capture or a live recovery.
function regionPlan({imageId,rect,blockSamples=LIMIT.samplesPerBlock,session,hostPid,requestId},captureId) {
  const options={imageId,rect,blockSamples,session,hostPid,requestId};
  const {width,height,tileWidth,tileHeight}=regionLayout(options);
  const identity=captureId===null?options:{...options,captureId};
  const prefix='region-'+hash(canonical(identity)).slice(0,32);"""
assert a in s;s=s.replace(a,b,1)
a="""function checkReply(reply,request) {"""
b="""export function planRegion(options) {
  check(typeof options.captureId==='string'&&/^[a-f0-9]{32}$/.test(options.captureId),
    'Explicit persisted capture ID required for request isolation');
  return regionPlan(options,options.captureId);
}

function checkReply(reply,request) {"""
s=s.replace(a,b,1)
s=s.replace("  const plan=planRegion({imageId,rect,session,hostPid,blockSamples,requestId});", "  const planning={imageId,rect,session,hostPid,blockSamples,requestId};\n  regionLayout(planning); // Validate bounds before filesystem changes; no wire IDs yet.\n  let plan;",1)
a="""      check(equal(journal.plan,plan)&&journal.blocks.every((b,i)=>equal(b.request,plan.blocks[i]?.request))&&journal.blocks.length===plan.blocks.length,'Original saved plan changed');"""
b="""      check(typeof journal.capture_id==='string'&&/^[a-f0-9]{32}$/.test(journal.capture_id),'Invalid saved capture identity');
      const legacy=!Object.hasOwn(journal,'request_namespace_version');
      if(legacy) {
        // Completed files are historical evidence only. Incomplete legacy IDs
        // may already collide with another export; never query/replay them here.
        check(journal.state==='CAPTURED','LEGACY_REGION_RECOVERY_UNSAFE: preserve old files; start a new export ID in a new output directory');
        plan=regionPlan(planning,null);
      } else {
        check(journal.request_namespace_version===2,'Unsupported region request namespace version');
        check(journal.workspace_realpath===workspace,'Journal belongs to another output directory/workspace; copied recovery is not supported');
        plan=planRegion({...planning,captureId:journal.capture_id});
      }
      check(equal(journal.plan,plan)&&Array.isArray(journal.blocks)&&journal.blocks.every((b,i)=>equal(b.request,plan.blocks[i]?.request))&&
        journal.blocks.length===plan.blocks.length&&equal(journal.status?.request,plan.status.request),'Original saved plan changed');"""
assert a in s;s=s.replace(a,b,1)
s=s.replace("      if(journal.state==='CAPTURED')return verifiedCapture(target,journal,plan);", "      if(journal.state==='CAPTURED') {\n        const receipt=verifiedCapture(target,journal,plan);\n        return legacy?{...receipt,request_namespace_status:'legacy_unscoped_saved_evidence_only'}:receipt;\n      }",1)
a="""      journal={schema_version:1,state:'CAPTURING',capture_mode:'native_chunked_read',capture_id:randomUUID().replaceAll('-',''),parameters,"""
b="""      const captureId=randomUUID().replaceAll('-','');
      plan=planRegion({...planning,captureId});
      journal={schema_version:1,request_namespace_version:2,workspace_realpath:workspace,
        state:'CAPTURING',capture_mode:'native_chunked_read',capture_id:captureId,parameters,"""
assert a in s;s=s.replace(a,b,1)
p.write_text(s)
p=root/'tests/native-region-handoff.test.mjs';s=p.read_text();s=s.replace("const plan=planRegion(opts('unused')),covered=new Set();", "const planning={...opts('unused'),captureId:'a'.repeat(32)};\n  const plan=planRegion(planning),covered=new Set();")
s=s.replace("planRegion({...opts('unused'),rect:","planRegion({...planning,rect:")
s=s.replace("planRegion({...opts('unused'),...bad})","planRegion({...planning,...bad})")
p.write_text(s)
p=root/'server.mjs';s=p.read_text()
a='    const content = [{type: "text", text: JSON.stringify(output, null, 2)}];'
b='''    // SHOW confirms document delivery, not the active workspace or GUI focus.
    // Also annotate recovered historical SHOWs; this is adapter policy, not
    // a fresh visibility probe or a rewrite of the stored native receipt.
    if (reply.state === "completed" && reply.original_operation === "SHOW") {
      output.display_context = {
        scope: "document_delivery_only",
        active_workspace_visibility: "unknown",
        workspace_activation_requested: false,
        model_visual_verification: false,
        observation: "not_performed_by_mcp",
      };
    }
    const content = [{type: "text", text: JSON.stringify(output, null, 2)}];'''
assert s.count(a)==1;s=s.replace(a,b,1);p.write_text(s)
