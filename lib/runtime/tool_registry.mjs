import {RpcError,validate} from './schema.mjs';

const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const text=v=>typeof v==='string'&&v.trim().length>0;
const strings=v=>Array.isArray(v)&&v.every(text);
function need(ok,message){if(!ok)throw new TypeError('ToolRegistry: '+message);}
function freeze(value){if(value&&typeof value==='object'){for(const item of Object.values(value))freeze(item);Object.freeze(value);}return value;}
function json(value,seen=new Set()){
  if(value===null||['string','boolean'].includes(typeof value))return;
  if(typeof value==='number'){need(Number.isFinite(value),'metadata must be finite JSON');return;}
  need(object(value)||Array.isArray(value),'definition/contract must be JSON data');
  if(Array.isArray(value))need(Object.keys(value).length===value.length&&Array.from({length:value.length},(_,i)=>Object.hasOwn(value,i)).every(Boolean),'sparse or extended metadata array');
  else need(Object.getPrototypeOf(value)===Object.prototype||Object.getPrototypeOf(value)===null,'metadata must use plain JSON objects');
  need(!seen.has(value),'cyclic definition/contract');seen.add(value);
  for(const item of Object.values(value))json(item,seen);seen.delete(value);
}
function snapshot(value){json(value);return freeze(structuredClone(value));}

// Registration checks schema shape, not scientific qualification. Cross-field
// semantics and the exact ABI/data guards stay in their existing adapters.
export function checkSchema(schema,root=true,depth=0,partial=false){
  need(object(schema)&&depth<=32,'invalid/overdeep input schema');
  const types=Array.isArray(schema.type)?schema.type:[schema.type];
  need(schema.type!==undefined||partial,'schema requires an explicit type');
  if(schema.type!==undefined)need(types.length>0&&new Set(types).size===types.length&&types.every(t=>['object','array','string','integer','number','boolean','null'].includes(t)),'invalid schema type');
  if(root)need(schema.type==='object'&&object(schema.properties),'tool input must be an object with properties');
  if(schema.properties!==undefined){need(object(schema.properties),'invalid properties');for(const v of Object.values(schema.properties))checkSchema(v,false,depth+1);}
  if(types.includes('object'))need(object(schema.properties),'object schema requires properties');
  if(types.includes('array')){need(object(schema.items),'array schema requires items');checkSchema(schema.items,false,depth+1);}
  if(schema.required!==undefined)need(strings(schema.required)&&new Set(schema.required).size===schema.required.length&&(!schema.properties||schema.required.every(k=>Object.hasOwn(schema.properties,k))),'invalid required properties');
  if(schema.additionalProperties!==undefined)need(typeof schema.additionalProperties==='boolean','invalid additionalProperties');
  if(schema.enum!==undefined)need(Array.isArray(schema.enum)&&schema.enum.length>0,'invalid enum');
  for(const k of ['minLength','maxLength','minItems','maxItems'])if(schema[k]!==undefined)need(Number.isSafeInteger(schema[k])&&schema[k]>=0,'invalid '+k);
  for(const k of ['minimum','maximum'])if(schema[k]!==undefined)need(typeof schema[k]==='number'&&Number.isFinite(schema[k]),'invalid '+k);
  for(const [lo,hi] of [['minimum','maximum'],['minLength','maxLength'],['minItems','maxItems']])if(schema[lo]!==undefined&&schema[hi]!==undefined)need(schema[lo]<=schema[hi],'reversed '+lo+'/'+hi);
  if(schema.pattern!==undefined){need(typeof schema.pattern==='string','invalid pattern');new RegExp(schema.pattern);}
  for(const k of ['oneOf','anyOf','allOf'])if(schema[k]!==undefined){need(Array.isArray(schema[k])&&schema[k].length>0,'invalid '+k);schema[k].forEach(s=>checkSchema(s,false,depth+1,true));}
  if(schema.not!==undefined)checkSchema(schema.not,false,depth+1,true);
}
function checkContract(c){
  need(object(c)&&text(c.backend)&&strings(c.inputs)&&strings(c.outputs),'missing backend/scientific inputs/outputs');
  need(object(c.effects)&&text(c.effects.kind)&&typeof c.effects.sourceMutation==='boolean'&&['required','optional','query','none'].includes(c.effects.requestId),'invalid side-effect/request identity contract');
  need(strings(c.gates),'missing delegated capability gates');
  need(object(c.execution)&&strings(c.execution.resourceKeys)&&text(c.execution.serialization)&&strings(c.execution.budgets)&&text(c.execution.cancellation),'missing execution constraints');
  need(object(c.recovery)&&text(c.recovery.method)&&text(c.recovery.scope)&&(c.recovery.tool===null||text(c.recovery.tool))&&(c.recovery.idField===null||text(c.recovery.idField)),'missing original-request recovery contract');
}

export class ToolRegistry {
  #tools=new Map();#modules=new Map();#unknown;#sealed=false;
  constructor({unknownTool=name=>`未知工具: ${name}`}={}){need(typeof unknownTool==='function','unknownTool must be a function');this.#unknown=unknownTool;}
  register(module){
    need(!this.#sealed,'registry composition is sealed');
    need(object(module)&&text(module.id)&&module.enabled===true,'module must be explicitly enabled');
    need(!this.#modules.has(module.id),'duplicate module '+module.id);
    need(Array.isArray(module.tools)&&module.tools.length>0&&typeof module.instructions==='string','module needs tools/instructions');
    need(module.close===undefined||typeof module.close==='function','invalid module close handler');
    const additions=new Map();
    for(const entry of module.tools){
      const d=entry?.definition;need(object(d)&&typeof d.name==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(d.name)&&typeof d.description==='string','invalid MCP tool definition');
      need(!this.#tools.has(d.name)&&!additions.has(d.name),'duplicate tool '+d.name);
      need(typeof entry.execute==='function','missing handler for '+d.name);checkSchema(d.inputSchema);checkContract(entry.contract);
      additions.set(d.name,{moduleId:module.id,definition:snapshot(d),contract:snapshot(entry.contract),execute:entry.execute});
    }
    // Commit only after every entry validates, so a failed registration cannot
    // partially expose tools or shadow a previous backend.
    for(const [name,entry]of additions)this.#tools.set(name,entry);
    this.#modules.set(module.id,{instructions:module.instructions,names:[...additions.keys()],close:module.close});
    return this;
  }
  unregister(id){need(!this.#sealed,'registry composition is sealed');const m=this.#modules.get(id);if(!m)return false;for(const name of m.names)this.#tools.delete(name);this.#modules.delete(id);m.close?.();return true;}
  seal(){this.#sealed=true;return this;}
  listTools(){return [...this.#tools.values()].map(e=>structuredClone(e.definition));}
  describe(name){const e=this.#tools.get(name);return e?{...structuredClone(e.contract),contractVersion:1,name,moduleId:e.moduleId,availability:{registered:true,runtimeQualification:'not_probed',authority:'Existing adapter validates each actual call; catalog presence is not qualification'}}:null;}
  describeAll(){return [...this.#tools.keys()].map(n=>this.describe(n));}
  instructions(){return [...this.#modules.values()].map(m=>m.instructions).filter(Boolean).join('\n');}
  async call(name,args,{signal}={}){const e=this.#tools.get(name);if(!e)throw new RpcError(-32602,this.#unknown(name));args=args===undefined?{}:args;validate(args,e.definition.inputSchema);return e.execute(args,{signal});}
  close(){for(const m of this.#modules.values())m.close?.();}
}
