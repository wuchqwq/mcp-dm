import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, writeFileSync, readFileSync, existsSync, mkdirSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../',import.meta.url));
const windows={skip:process.platform!=='win32'&&'Windows PowerShell registration adapter'};
function fixture(t){
  const directory=mkdtempSync(path.join(tmpdir(),'mcp-codex-setup-'));
  t.after(()=>rmSync(directory,{recursive:true,force:true}));
  const record=path.join(directory,'registration.json'),catalog=path.join(directory,'catalog.json');
  const codex=path.join(directory,'codex-test.ps1'),python=path.join(directory,'python-test.ps1');
  writeFileSync(catalog,'[]');
  writeFileSync(python,`if ($env:TEST_PYTHON_FAIL -eq '1') { exit 3 }; exit 0\n`);
  writeFileSync(codex,`$ErrorActionPreference='Stop'
if ($args[0] -ne 'mcp') { throw 'Only MCP commands expected' }
switch ($args[1]) {
  'list' { Get-Content -LiteralPath $env:TEST_CODEX_CATALOG -Raw; exit 0 }
  'add' { ConvertTo-Json -InputObject @($args) -Compress | Set-Content -LiteralPath $env:TEST_CODEX_RECORD; exit 0 }
  'get' {
    $saved=Get-Content -LiteralPath $env:TEST_CODEX_RECORD -Raw | ConvertFrom-Json
    # Keep the shim compatible with both PowerShell editions. The command
    # and script path are the final two arguments in the native CLI contract.
    @{name=$saved[2];transport=@{command=$saved[-2];args=@($saved[-1])}} | ConvertTo-Json -Depth 4; exit 0
  }
  default { throw 'Unexpected MCP command' }
}
`);
  const env={...process.env,TEST_CODEX_RECORD:record,TEST_CODEX_CATALOG:catalog};
  function run(script,args=[],extraEnv={}){
    return spawnSync('powershell.exe',['-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',path.join(root,'setup',script),...args],{env:{...env,...extraEnv},encoding:'utf8',timeout:20000});
  }
  const common=['-CodexExecutable',codex,'-NodeExecutable',process.execPath];
  const images=['-Backend','images','-ImageWorkspace',path.join(directory,'images with space'),'-ImagePython',python,'-ContextWorkspace',path.join(directory,'contexts')];
  return {directory,record,catalog,python,run,common,images,added:()=>JSON.parse(readFileSync(record,'utf8').replace(/^\uFEFF/,''))};
}
function envArgs(args){const result={};for(let i=0;i<args.length;i++)if(args[i]==='--env'){const item=args[++i],equals=item.indexOf('=');result[item.slice(0,equals)]=item.slice(equals+1);}return result;}
function success(result){assert.equal(result.status,0,result.stdout+'\n'+result.stderr);}

test('Codex default registration retains the Python bridge gates and legacy port/analysis options',windows,t=>{
  const f=fixture(t);success(f.run('register_codex.ps1',[...f.common,'-Port','9876','-AnalysisPython',f.python]));
  const args=f.added(),env=envArgs(args);assert.equal(args[2],'digitalmicrograph');assert.equal(env.DM_MCP_BACKEND,'python');
  assert.equal(env.DM_BRIDGE_HOST,'127.0.0.1');assert.equal(env.DM_BRIDGE_PORT,'9876');assert.equal(env.DM_MCP_ALLOW_DMSCRIPT,'0');
  assert.equal(env.DM_ANALYSIS_PYTHON,f.python);assert.equal(env.DM_IMAGE_WORKSPACE,undefined);
});
test('Codex explicit images registration adds independent image/context/optional structure paths without a bridge',windows,t=>{
  const f=fixture(t);success(f.run('register_codex.ps1',[...f.common,...f.images,'-Name','microscopy-images','-StructureWorkspace',path.join(f.directory,'structures'),'-StructurePython',f.python,'-ExecutionObservability']));
  const args=f.added(),env=envArgs(args);assert.equal(args[2],'microscopy-images');assert.equal(env.DM_MCP_BACKEND,'images');
  assert.equal(env.DM_IMAGE_WORKSPACE,path.join(f.directory,'images with space'));assert.equal(env.DM_IMAGE_PYTHON,f.python);
  assert.equal(env.DM_ANALYSIS_CONTEXT_WORKSPACE,path.join(f.directory,'contexts'));assert.equal(env.DM_STRUCTURE_PYTHON,f.python);
  assert.equal(env.DM_MCP_EXECUTION_OBSERVABILITY,'1');assert.equal(env.DM_BRIDGE_HOST,undefined);assert.equal(env.DM_MCP_ALLOW_DMSCRIPT,'0');
  assert.equal(existsSync(env.DM_IMAGE_WORKSPACE),false,'registration must not create science data');
});
test('Codex duplicate names refuse before add and preserve the existing catalog',windows,t=>{
  const f=fixture(t),saved='[{"name":"digitalmicrograph","unrelated":"preserve"}]';writeFileSync(f.catalog,saved);
  const result=f.run('register_codex.ps1',f.common);assert.notEqual(result.status,0);assert.match(result.stderr,/already exists/);
  assert.equal(existsSync(f.record),false);assert.equal(readFileSync(f.catalog,'utf8'),saved);
});
test('Codex images input/preflight failures never write a registration',windows,t=>{
  const f=fixture(t);
  for(const args of [f.common.concat('-Backend','images'),f.common.concat('-Backend','images','-ImageWorkspace','relative-output','-ImagePython',f.python),f.common.concat('-StructureWorkspace',path.join(f.directory,'structures'))]){
    const result=f.run('register_codex.ps1',args);assert.notEqual(result.status,0);assert.equal(existsSync(f.record),false);
  }
  const failed=f.run('register_codex.ps1',[...f.common,...f.images],{TEST_PYTHON_FAIL:'1'});assert.notEqual(failed.status,0);assert.match(failed.stderr,/preflight failed/);assert.equal(existsSync(f.record),false);
});
test('Codex CheckOnly validates a new image registration without writes',windows,t=>{
  const f=fixture(t);const result=f.run('register_codex.ps1',[...f.common,...f.images,'-CheckOnly']);success(result);
  assert.match(result.stdout,/Preflight passed/);assert.equal(existsSync(f.record),false);assert.equal(existsSync(path.join(f.directory,'contexts')),false);
});
test('Codex explicit Skill install keeps all sibling links and refuses any pre-existing name',windows,t=>{
  const f=fixture(t),target=path.join(f.directory,'skills');
  const check=f.run('install_codex_skills.ps1',['-SkillsDirectory',target,'-CheckOnly']);success(check);assert.equal(existsSync(target),false);
  success(f.run('install_codex_skills.ps1',['-SkillsDirectory',target]));
  const router=readFileSync(path.join(target,'microscopy-router','SKILL.md'),'utf8');
  for(const match of router.matchAll(/\]\((\.\.\/[^)]+)\)/g))assert.equal(existsSync(path.resolve(target,'microscopy-router',match[1])),true,match[1]);
  const before=readFileSync(path.join(target,'microscopy-router','SKILL.md'),'utf8');
  const again=f.run('install_codex_skills.ps1',['-SkillsDirectory',target]);assert.notEqual(again.status,0);assert.match(again.stderr,/already exists/);
  assert.equal(readFileSync(path.join(target,'microscopy-router','SKILL.md'),'utf8'),before);
  const partial=path.join(f.directory,'partial');mkdirSync(path.join(partial,'crystallography-compare'),{recursive:true});
  const conflict=f.run('install_codex_skills.ps1',['-SkillsDirectory',partial]);assert.notEqual(conflict.status,0);assert.equal(existsSync(path.join(partial,'microscopy-router')),false,'preflight every target before copying any Skill');
});
