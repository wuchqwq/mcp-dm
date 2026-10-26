// Trusted, explicit composition root. No filesystem discovery/import paths from
// user data. Adding a module changes this list or passes additionalModules;
// the protocol server and registry dispatch never learn its tool names.
import {createDMPythonModule} from './dm_python_module.mjs';
import {createDMNativeModule} from './dm_native_module.mjs';
import {createImageModule} from './image_module.mjs';
import {createImagePanelModule} from './image_panel_module.mjs';
import {createStructureModule} from './structure_module.mjs';

export const OPTIONAL_MODULE_IDS=Object.freeze(['images','image-panel','structures']);
export function builtinModules({env,backend,disabled}){
  const modules=[];
  if(backend==='python')modules.push(createDMPythonModule({env}));
  if(backend==='native')modules.push(createDMNativeModule({env}));
  if(!disabled.has('images')&&(env.DM_IMAGE_WORKSPACE||backend==='images')){
    const image=createImageModule({workspaceOptions:{workspace:env.DM_IMAGE_WORKSPACE,python:env.DM_IMAGE_PYTHON||env.DM_ANALYSIS_PYTHON||'python'}});modules.push(image);
    if(!disabled.has('image-panel'))modules.push(createImagePanelModule({imageWorkspace:image.workspace}));
  }
  if(!disabled.has('structures')&&env.DM_STRUCTURE_WORKSPACE)modules.push(createStructureModule({workspaceOptions:{workspace:env.DM_STRUCTURE_WORKSPACE,python:env.DM_STRUCTURE_PYTHON||'python'},viewerAssetPath:env.DM_STRUCTURE_VIEWER_ASSET??null}));
  return modules;
}
