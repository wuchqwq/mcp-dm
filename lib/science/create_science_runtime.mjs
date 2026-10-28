// Standalone provider for macOS/Linux/Windows file-based microscopy.
// Do not import the DM composition root or Gatan/native adapters here.
import os from 'node:os';
import path from 'node:path';
import {ToolRegistry} from '../runtime/tool_registry.mjs';
import {ExecutionCoordinator} from '../runtime/execution_coordinator.mjs';
import {createImageModule} from '../tools/image_module.mjs';
import {createImagePanelModule} from '../tools/image_panel_module.mjs';
import {createStructureModule} from '../tools/structure_module.mjs';
import {createExecutionModule} from '../tools/execution_module.mjs';
import {createAnalysisContextModule} from '../tools/analysis_context_module.mjs';

function absoluteDirectory(value, setting) {
  if(typeof value!=='string'||!value.trim()||!path.isAbsolute(value)) {
    throw new Error(setting+' must be an absolute directory path');
  }
  return path.resolve(value);
}
function enabledFlag(env,key,defaultValue='0') {
  const value=env[key]??defaultValue;
  if(!['0','1'].includes(value))throw new Error(key+' must be 0 or 1');
  return value==='1';
}

export function createScienceRuntime({env=process.env,coordinator=new ExecutionCoordinator()}={}){
  // Explicit opt-in for optional components; the image route is always present.
  const imageDirectory=absoluteDirectory(
    env.MICROSCOPY_IMAGE_WORKSPACE??path.join(os.homedir(),'.microscopy-core','images'),
    'MICROSCOPY_IMAGE_WORKSPACE');
  const structureDirectory=env.MICROSCOPY_STRUCTURE_WORKSPACE
    ?absoluteDirectory(env.MICROSCOPY_STRUCTURE_WORKSPACE,'MICROSCOPY_STRUCTURE_WORKSPACE'):null;
  const contextDirectory=env.MICROSCOPY_CONTEXT_WORKSPACE
    ?absoluteDirectory(env.MICROSCOPY_CONTEXT_WORKSPACE,'MICROSCOPY_CONTEXT_WORKSPACE'):null;
  const panel=enabledFlag(env,'MICROSCOPY_PANEL','1');
  const observer=enabledFlag(env,'MICROSCOPY_EXECUTION_OBSERVABILITY','0');
  const image=createImageModule({workspaceOptions:{
    workspace:imageDirectory,python:env.MICROSCOPY_PYTHON||'python3',coordinator,
  }});
  const modules=[image];
  if(panel)modules.push(createImagePanelModule({imageWorkspace:image.workspace}));
  const providers={image:image.workspace};
  if(structureDirectory){
    const structure=createStructureModule({
      workspaceOptions:{workspace:structureDirectory,python:env.MICROSCOPY_STRUCTURE_PYTHON||env.MICROSCOPY_PYTHON||'python3',coordinator},
      viewerAssetPath:env.MICROSCOPY_STRUCTURE_VIEWER_ASSET??null,
    });
    modules.push(structure);
    providers.structure=structure.workspace;
  }
  if(observer)modules.push(createExecutionModule({coordinator,providers:Object.fromEntries(
    Object.entries(providers).map(([name,workspace])=>[name,workspace.requestScope]))}));
  if(contextDirectory)modules.push(createAnalysisContextModule({directory:contextDirectory,providers}));
  const registry=new ToolRegistry({unknownTool:name=>
    'Independent microscopy-core does not provide '+name+'; DM tools belong to the separate mcp-dm provider, with no implicit fallback'});
  try{
    for(const module of modules)registry.register(module);
    registry.seal();
  }catch(error){registry.close();throw error;}
  return {registry,instructions:registry.instructions(),backend:'science',coordinator,providers,
    close:()=>registry.close()};
}
