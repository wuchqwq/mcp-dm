// The independent DM provider owns only DM tools; no scientific workspace import.
import {ToolRegistry} from '../runtime/tool_registry.mjs';
import {createDMPythonModule} from './dm_python_module.mjs';
import {createDMNativeModule} from './dm_native_module.mjs';

export function createDMRuntime({env=process.env}={}) {
  const backend=env.DM_MCP_BACKEND??'python';
  if(!['python','native'].includes(backend)) {
    throw new Error('The standalone DM provider accepts python or native only. Use microscopy-core for independent image/structure tools. No implicit backend fallback.');
  }
  const timeout=Number(env.DM_MCP_TIMEOUT_MS||30000);
  if(!Number.isFinite(timeout)||timeout<100||timeout>600000)throw new Error('Invalid timeout (100..600000 ms)');
  const registry=new ToolRegistry({unknownTool:name=>`DM provider does not provide ${name}; configure the separate science MCP for image/structure tools.`});
  try {
    registry.register(backend==='native'?createDMNativeModule({env}):createDMPythonModule({env}));
    registry.seal();
  } catch(error) {registry.close();throw error;}
  return {registry,instructions:registry.instructions(),backend,close:()=>registry.close()};
}
