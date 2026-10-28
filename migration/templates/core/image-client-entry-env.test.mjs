import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {StdioImageClient} from '../tools/image_panel.mjs';

test('panel client forwards its exact workspace/interpreter to legacy and independent entry points',async()=>{
  const directory=mkdtempSync(path.join(tmpdir(),'panel-entry-env-'));
  const server=path.join(directory,'inspect.mjs'),workspace=path.join(directory,'chosen-workspace'),python=path.join(directory,'chosen-python');
  writeFileSync(server,`process.stdin.setEncoding('utf8');let b='';process.stdin.on('data',c=>{b+=c;let n;while((n=b.indexOf('\\n'))>=0){const m=JSON.parse(b.slice(0,n));b=b.slice(n+1);process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result:Object.fromEntries(Object.entries(process.env).filter(([k])=>k.startsWith('DM_')||k.startsWith('MICROSCOPY_')))})+'\\n');}});`);
  const names=['MICROSCOPY_IMAGE_WORKSPACE','MICROSCOPY_PYTHON','MICROSCOPY_STRUCTURE_WORKSPACE','MICROSCOPY_CONTEXT_WORKSPACE'];
  const prior=Object.fromEntries(names.map(k=>[k,process.env[k]]));
  for(const key of names)process.env[key]='inherited-but-wrong';
  let client;
  try {
    client=new StdioImageClient({workspace,python,serverPath:server});
    const {result}=await client.rpc('inspect');
    assert.equal(result.DM_MCP_BACKEND,'images');assert.equal(result.DM_IMAGE_WORKSPACE,workspace);assert.equal(result.DM_IMAGE_PYTHON,python);
    assert.equal(result.MICROSCOPY_IMAGE_WORKSPACE,workspace);assert.equal(result.MICROSCOPY_PYTHON,python);
    assert.equal(result.MICROSCOPY_CONTEXT_WORKSPACE,'');assert.equal(result.MICROSCOPY_STRUCTURE_WORKSPACE,'');
  } finally {
    if(client)await client.close();
    for(const key of names){if(prior[key]===undefined)delete process.env[key];else process.env[key]=prior[key];}
    rmSync(directory,{recursive:true,force:true});
  }
});
