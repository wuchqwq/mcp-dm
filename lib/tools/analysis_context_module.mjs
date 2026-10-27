// Optional, extraction-ready composition of context storage + provider ports.
// No scientific algorithm or second scientific request journal lives here.
import {AnalysisContext,ANALYSIS_ROLES,contextFingerprints,requiredContextDependencies} from '../runtime/analysis_context.mjs';
import {FileContextStore} from '../runtime/file_context_store.mjs';
import {createScientificContextBindings,sameScientificGrid} from '../analysis_context_bindings.mjs';
import {tool} from '../runtime/schema.mjs';

const id={type:'string',minLength:1,maxLength:64,pattern:'^[A-Za-z0-9_-]+$'};
const ref={type:'object',additionalProperties:false,required:['provider','object_id'],properties:{provider:{type:'string',enum:['image','structure']},object_id:{type:'string',minLength:32,maxLength:32,pattern:'^[a-f0-9]{32}$'}}};
const selections={type:'object',additionalProperties:false,properties:Object.fromEntries(ANALYSIS_ROLES.map(role=>[role,['points','measurements'].includes(role)
  ? {type:['array','null'],minItems:1,maxItems:64,items:ref}
  : {...ref,type:['object','null']}]))};
const reason={type:'string',minLength:1,maxLength:2000};
export const analysisTools=[
  tool('analysis_create','Create a named lightweight current analysis. Save analysis_id and request_id first. Stores scoped immutable references only; no data copying, science execution or required workflow. Old tools remain directly callable.',{analysis_id:id,request_id:id,reason},['analysis_id','request_id','reason']),
  tool('analysis_read','Read current or historical analysis references. Specify revision OR original context request_id to recover an exact mutation; omit both for current. This is not a fresh observation of DM or scientific revalidation.',{analysis_id:id,revision:{type:'integer',minimum:1,maximum:1024},request_id:id},['analysis_id']),
  tool('analysis_update','CAS-promote explicit saved scientific references after provider validation. Selections use configured image/structure aliases; scope/dependency fingerprints are resolved internally. Display-only changes preserve measurements; geometry changes stale dependent results. Late old-revision outcomes stay historical and never overwrite current. No scientific operation is retried or rolled back.',{analysis_id:id,expected_revision:{type:'integer',minimum:1,maximum:1024},request_id:id,reason,selections},['analysis_id','expected_revision','request_id','reason','selections']),
  tool('analysis_proposal','Inspect a saved historical CAS proposal without applying it or re-executing science.',{analysis_id:id,proposal_id:id},['analysis_id','proposal_id']),
];

export function createAnalysisContextModule({directory,providers,store=new FileContextStore({directory})}={}) {
  if(!providers||!Object.keys(providers).length)throw new TypeError('Analysis context needs explicit scientific provider ports');
  const contextFor=signal=>{
    const binding=createScientificContextBindings({providers,signal});
    return {context:new AnalysisContext({store,...binding}),...binding};
  };
  const scoped=selected=>{
    const workspace=providers[selected.provider];
    if(!workspace)throw new Error('Selected scientific provider is not enabled');
    return {...workspace.requestScope,objectId:selected.object_id};
  };
  const entries=value=>value===null||value===undefined?[]:Array.isArray(value)?value:[value];
  async function selectedChanges(context,binding,args) {
    const base=await context.read(args.analysis_id,args.expected_revision),slots=structuredClone(base.slots),changes={};
    const selections=structuredClone(args.selections);
    if(!Object.keys(selections).length)throw new Error('Select at least one explicit context role');
    // Resolve once per call; the core uses these same verified cached provider
    // proofs. No unverified caller hashes or private arbitrary file paths.
    for(const [role,value] of Object.entries(selections)) {
      if(value===null){slots[role]=null;changes[role]=null;continue;}
      const make=async selected=>{const full=scoped(selected);return {ref:full,proof:await binding.resolveReference(full),dependsOn:{},status:'active',staleBecause:[]};};
      slots[role]=Array.isArray(value)?await Promise.all(value.map(make)):await make(value);
    }
    // A sourced reciprocal centre revision is also a new calibration record.
    // Keep already-selected geometry roles on that one verified wrapper instead
    // of demanding that the caller manually duplicate a selection. Explicitly
    // supplied pairs are validated as supplied, never silently reconciled.
    for(const [changed,paired] of [['center','calibration'],['calibration','center']]) {
      if(Object.hasOwn(args.selections,changed)&&!Object.hasOwn(args.selections,paired)&&selections[changed]&&base.slots[paired]&&slots[changed].proof.roles.includes(paired)) {
        slots[paired]=structuredClone(slots[changed]);selections[paired]=structuredClone(selections[changed]);
      }
    }
    const fingerprints=contextFingerprints(slots);
    for(const [role,value] of Object.entries(selections)) {
      if(value===null)continue;
      const planned=entries(slots[role]).map(entry=>{
        const {required,parents}=requiredContextDependencies(role,slots),dependsOn=Object.fromEntries(required.map(key=>[key,fingerprints[key]]));
        if(parents.length){
          const parent=parents.find(key=>sameScientificGrid(slots[key]?.proof.scientific?.grid,entry.proof.scientific?.grid));
          if(!parent)throw new Error('Selected '+role+' does not match the current experiment or FFT scientific grid');
          dependsOn[parent]=fingerprints[parent];
        }
        return {ref:entry.ref,dependsOn};
      });
      changes[role]=Array.isArray(value)?planned:planned[0];
    }
    return changes;
  }
  return {id:'analysis-context',enabled:true,instructions:'Optional analysis_* tools keep named current references and CAS revisions. They never require a fixed analysis workflow or replace provider result queries. Read the revision before work; save scientific outcomes first; promote only against that revision. Historical proposals are not current.',
    tools:analysisTools.map(definition=>({definition,
      contract:{backend:'external-analysis-context',inputs:['ScopedScientificRef:configured provider/workspace/session/object','AnalysisRevision:explicit current or historical revision'],outputs:['ContextRevisionRef:immutable references and dependency freshness, no copied science'],
        effects:{kind:['analysis_create','analysis_update'].includes(definition.name)?'context-revision-write':'inspect',sourceMutation:false,requestId:['analysis_create','analysis_update'].includes(definition.name)?'required':'none'},
        gates:['Existing provider object/hash/identity validation and exact scientific dependency bindings','Filesystem CAS/hash-linked context history; no scientific result authority duplicated'],
        execution:{resourceKeys:[],serialization:'Bounded context CAS independent of worker capacity; provider proof reads use reserved query capacity',budgets:['Context <=96 KiB references; revision <=128 KiB; bounded immutable history; no scientific array copies'],cancellation:'Stop proof reads/waiting; provider outcomes already saved are not rolled back or replayed'},
        recovery:{method:'Read the named analysis using original context request_id or explicit revision; query science in its provider',tool:'analysis_read',idField:'request_id',scope:'Explicit context store plus analysis identity; scoped scientific refs remain in original workspaces'}},
      execute:async(args,{signal}={})=>{
        const binding=contextFor(signal),context=binding.context;let result;
        try {
          if(definition.name==='analysis_create')result=await context.create({analysisId:args.analysis_id,requestId:args.request_id,reason:args.reason});
          else if(definition.name==='analysis_read') {
            if(args.revision!==undefined&&args.request_id!==undefined)throw new Error('Choose revision or original context request_id, never both');
            result=args.request_id?await context.readRequest(args.analysis_id,args.request_id):{state:'read',context:await context.read(args.analysis_id,args.revision)};
          } else if(definition.name==='analysis_proposal')result={state:'historical',proposal:await context.readProposal(args.analysis_id,args.proposal_id)};
          else {
            // Resolve the explicit selections against the revision read before
            // work; the core owns context mutation deduplication and CAS.
            const changes=await selectedChanges(context,binding,args);
            result=await context.commit({analysisId:args.analysis_id,expectedRevision:args.expected_revision,requestId:args.request_id,changes,reason:args.reason});
          }
          return {content:[{type:'text',text:JSON.stringify({backend:'external-analysis-context',...result},null,2)}]};
        } catch(error) {if(error.code)error.message=error.code+': '+error.message;throw error;}
      },
    }))};
}
