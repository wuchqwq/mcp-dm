// Source-bound full public catalog parity; no DM calls or scientific workers.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const source=process.env.SPLIT_SOURCE_ROOT,output=process.env.SPLIT_OUTPUT_ROOT;
if(!source||!output||!path.isAbsolute(source)||!path.isAbsolute(output))throw new Error('Set explicit absolute SPLIT_SOURCE_ROOT and SPLIT_OUTPUT_ROOT');
const load=(root,file)=>import(pathToFileURL(path.join(root,file)).href);
const original=await load(source,'lib/tools/create_server_runtime.mjs');
const originalScience=await load(source,'lib/science/create_science_runtime.mjs');
const dm=await load(path.join(output,'mcp-dm'),'lib/tools/create_dm_runtime.mjs');
const core=await load(path.join(output,'microscopy-core'),'lib/science/create_science_runtime.mjs');
for(const backend of ['python','native'])test(`DM ${backend}: exact original public tool definitions/instructions`,()=>{
 const env={DM_MCP_BACKEND:backend,DM_NATIVE_SESSION:'a'.repeat(32)};
 const before=original.createServerRuntime({env}),after=dm.createDMRuntime({env});
 try{assert.deepEqual(after.registry.listTools(),before.registry.listTools());assert.equal(after.instructions,before.instructions);}finally{before.close();after.close();}
});
for(const optional of [false,true])test(`science optional=${optional}: exact original public catalog/instructions`,()=>{
 const dir=mkdtempSync(path.join(tmpdir(),'split-parity-'));
 const env={MICROSCOPY_IMAGE_WORKSPACE:path.join(dir,'images'),MICROSCOPY_PYTHON:'__no_worker__',...(optional?{MICROSCOPY_STRUCTURE_WORKSPACE:path.join(dir,'structures'),MICROSCOPY_CONTEXT_WORKSPACE:path.join(dir,'contexts'),MICROSCOPY_EXECUTION_OBSERVABILITY:'1'}:{})};
 let before,after;
 try {before=originalScience.createScienceRuntime({env});after=core.createScienceRuntime({env});assert.deepEqual(after.registry.listTools(),before.registry.listTools());assert.equal(after.instructions,before.instructions);}
 finally {before?.close();after?.close();rmSync(dir,{recursive:true,force:true});}
});
test('DM-only runtime retains original timeout and backend admission',()=>{
 for(const value of ['99','600001','NaN','Infinity'])assert.throws(()=>dm.createDMRuntime({env:{DM_MCP_TIMEOUT_MS:value}}),/Invalid timeout/);
 assert.throws(()=>dm.createDMRuntime({env:{DM_MCP_BACKEND:'images'}}),/standalone DM provider/);
});
