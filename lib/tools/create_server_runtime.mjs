// mcp-dm provider composition only. The portable registry never imports this
// file; future cross-provider orchestration belongs to the Agent repository.
import {ToolRegistry} from '../runtime/tool_registry.mjs';
import {builtinModules,OPTIONAL_MODULE_IDS} from './builtin_modules.mjs';
import {ExecutionCoordinator} from '../runtime/execution_coordinator.mjs';
import {createExecutionModule} from './execution_module.mjs';
import {createAnalysisContextModule} from './analysis_context_module.mjs';

export function createServerRuntime({env=process.env,additionalModules=[],disabledModules,coordinator=new ExecutionCoordinator()}={}){
  const backend=env.DM_MCP_BACKEND===undefined?'python':env.DM_MCP_BACKEND;
  if(!['python','native','images'].includes(backend))throw new Error('DM_MCP_BACKEND must be python, native or images; no implicit backend fallback');
  const timeout=Number(env.DM_MCP_TIMEOUT_MS||30000);
  if(!Number.isFinite(timeout)||timeout<100||timeout>600000)throw new Error('Invalid timeout (100..600000 ms)');
  const ids=disabledModules??(env.DM_MCP_DISABLED_MODULES?env.DM_MCP_DISABLED_MODULES.split(',').map(s=>s.trim()):[]);
  if(!Array.isArray(ids))throw new Error('disabledModules must be an array of explicit built-in optional module IDs');
  for(const id of ids)if(!OPTIONAL_MODULE_IDS.includes(id))throw new Error(`Cannot disable unknown or core module ${id}; optional IDs: ${OPTIONAL_MODULE_IDS.join(',')}`);
  if(!Array.isArray(additionalModules))throw new TypeError('additionalModules must be explicitly supplied trusted module objects');
  const registry=new ToolRegistry({unknownTool:name=>backend==='images'?`独立图像模式不提供 ${name}；不连接或回退 DM`:backend==='native'?`native backend 不支持工具: ${name}；不会回退 Python`:`未知工具: ${name}`});
  const disabled=new Set(ids), modules=builtinModules({env,backend,disabled,coordinator});
  const providers=Object.fromEntries(modules.filter(module=>['images','structures'].includes(module.id)).map(module=>[module.id==='images'?'image':'structure',module.workspace]));
  if(env.DM_MCP_EXECUTION_OBSERVABILITY!==undefined&&!['0','1'].includes(env.DM_MCP_EXECUTION_OBSERVABILITY))throw new Error('DM_MCP_EXECUTION_OBSERVABILITY must be0 or1');
  try{
    if(env.DM_MCP_EXECUTION_OBSERVABILITY==='1'&&!disabled.has('execution-observer'))modules.push(createExecutionModule({coordinator,providers:Object.fromEntries(Object.entries(providers).map(([name,workspace])=>[name,workspace.requestScope]))}));
    if(env.DM_ANALYSIS_CONTEXT_WORKSPACE&&!disabled.has('analysis-context'))modules.push(createAnalysisContextModule({directory:env.DM_ANALYSIS_CONTEXT_WORKSPACE,providers}));
    for(const module of [...modules,...additionalModules])registry.register(module);
  }catch(error){registry.close();throw error;}
  registry.seal();
  // Legacy images-only initialize starts with a newline. Keep its exact bytes,
  // including descriptions, while optional modules declare their own text.
  const instructions=(backend==='images'&&registry.listTools().length?'\n':'')+registry.instructions();
  return {registry,instructions,backend,coordinator,providers,close:()=>registry.close()};
}
