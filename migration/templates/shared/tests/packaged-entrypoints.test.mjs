// Exported-package installation/docs checks. No real Codex config, host or network.
import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync,readFileSync,mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const root=fileURLToPath(new URL('../',import.meta.url));
const core=JSON.parse(readFileSync(path.join(root,'package.json'),'utf8')).name==='microscopy-core';
const read=name=>readFileSync(path.join(root,name),'utf8');

test('exported entry guides have resolvable local Markdown file links',()=>{
 const docs=['README.md','README.agent.md','AGENTS.md',...(core?['docs/CLIENT_SETUP.md','docs/RESEARCHER_DATA_INSPECTOR.md','docs/IMAGE_NUMERIC_INSPECTION.md']:['REFERENCE.md','REFERENCE.en.md'])];
 for(const name of docs){
  const text=read(name).replace(/```[\s\S]*?```/g,'');
  for(const match of text.matchAll(/\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)/g)){
   const href=match[1];if(/^(?:[a-z][a-z0-9+.-]*:|#)/i.test(href))continue;
   const local=decodeURIComponent(href.split('#')[0].split('?')[0]);if(!local)continue;
   const target=path.resolve(root,path.dirname(name),local),relative=path.relative(root,target);
   assert.ok(!relative.startsWith('..')&&!path.isAbsolute(relative),`${name}: link escapes package`);
   assert.ok(existsSync(target),`${name}: missing local link ${href}`);
  }
 }
});

if(core){
 test('core includes the four explicitly public synthetic inspector assets',()=>{
  for(const name of ['canvas-results.png','profile-workspace.png']){
   const data=readFileSync(path.join(root,'docs/examples/researcher-inspector',name));
   // Source screenshots have legacy .png names, including JPEG bytes. Keep
   // the original evidence byte-for-byte; the suffix is not its codec contract.
   const png=data.subarray(0,8).toString('hex')==='89504e470d0a1a0a';
   const jpeg=data.subarray(0,3).toString('hex')==='ffd8ff'&&data.subarray(-2).toString('hex')==='ffd9';
   assert.ok(data.length>8&&(png||jpeg),`${name}: expected a source PNG/JPEG screenshot`);
   const source=JSON.parse(read('MIGRATION_MANIFEST.json')).files.find(entry=>entry.path==='docs/examples/researcher-inspector/'+name);
   assert.equal(source?.source?.kind,'copied');
   assert.equal(createHash('sha256').update(data).digest('hex'),source.sha256,'screenshot must preserve its committed source bytes');
  }
  for(const name of ['measurements.csv','profile.csv'])assert.ok(read('docs/examples/researcher-inspector/'+name).trim().split('\n').length>1);
  assert.match(read('docs/CLIENT_SETUP.md'),/MICROSCOPY_IMAGE_WORKSPACE/);
  assert.match(read('README.agent.md'),/docs\/CLIENT_SETUP\.md/);
 });
}else{
 test('DM registrar matches python/native runtime and rejects obsolete science arguments',()=>{
  const script=read('setup/register_codex.ps1');
  assert.match(script,/\[CmdletBinding\(\)\]/);
  assert.match(script,/ValidateSet\('python','native'\)/);
  assert.doesNotMatch(script,/\$(?:ImageWorkspace|ImagePython|StructureWorkspace|StructurePython|ContextWorkspace|ExecutionObservability)\b/);
  assert.match(script,/DM_NATIVE_SESSION=\$NativeSession/);
  assert.match(script,/DM_MCP_ALLOW_DMSCRIPT=0/);
 });
 const hasPS=spawnSync('pwsh',['-NoProfile','-Command','exit 0'],{timeout:5000}).status===0;
 test('PowerShell registrar preflight, python/native arguments, duplicate and invalid refusals', {skip:hasPS?false:'PowerShell unavailable; live registrar NOT_TESTED here'},()=>{
  const dir=mkdtempSync(path.join(tmpdir(),'dm-registrar-'));
  const stub=path.join(dir,'fake-codex.ps1'),log=path.join(dir,'calls.jsonl'),saved=path.join(dir,'saved.json');
  writeFileSync(stub,`param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Tail)
[IO.File]::AppendAllText($env:STUB_LOG, (ConvertTo-Json -InputObject @($Tail) -Compress) + "\n")
if ($Tail[1] -eq 'list') { if ($env:STUB_DUP -eq '1') { '[{"name":"review-dm"}]' } else { '[]' }; exit 0 }
if ($Tail[1] -eq 'add') { $i=[Array]::IndexOf($Tail,'--'); @{name=$Tail[2];transport=@{command=$Tail[$i+1];args=@($Tail[$i+2])}} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $env:STUB_STATE; 'added'; exit 0 }
if ($Tail[1] -eq 'get') { Get-Content -Raw -LiteralPath $env:STUB_STATE; exit 0 }
exit 2
`);
  const calls=()=>existsSync(log)?readFileSync(log,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse):[];
  const invoke=(extra=[],environment={})=>spawnSync('pwsh',['-NoProfile','-NonInteractive','-File',path.join(root,'setup/register_codex.ps1'),'-Name','review-dm','-NodeExecutable',process.execPath,'-CodexExecutable',stub,...extra],{encoding:'utf8',timeout:15000,env:{...process.env,CODEX_HOME:path.join(dir,'unused-home'),STUB_LOG:log,STUB_STATE:saved,STUB_DUP:'0',...environment}});
  try{
   for(const backend of ['python','native']){
    const args=['-Backend',backend,...(backend==='native'?['-NativeSession','a'.repeat(32)]:[])];
    let n=calls().length,r=invoke([...args,'-CheckOnly']);assert.equal(r.status,0,r.stderr);assert.deepEqual(calls().slice(n),[['mcp','list','--json']]);
    n=calls().length;r=invoke(args);assert.equal(r.status,0,r.stderr);const added=calls().slice(n).find(x=>x[1]==='add');
    assert.ok(added.includes('DM_MCP_BACKEND='+backend));
    assert.equal(added.includes('DM_NATIVE_SESSION='+'a'.repeat(32)),backend==='native');
    assert.equal(added.includes('DM_BRIDGE_HOST=127.0.0.1'),backend==='python');
    assert.ok(!added.some(x=>/^(DM_(IMAGE|STRUCTURE|ANALYSIS_CONTEXT)_|MICROSCOPY_)/.test(x)));
   }
   const before=calls().length,r=invoke(['-CheckOnly'],{STUB_DUP:'1'});assert.notEqual(r.status,0);assert.deepEqual(calls().slice(before),[['mcp','list','--json']]);
   for(const args of [['-Backend','images'],['-Backend','native'],['-Backend','native','-NativeSession','invalid'],['-ImageWorkspace','invalid']]){
    const n=calls().length,r=invoke(args);assert.notEqual(r.status,0,JSON.stringify(args));assert.equal(calls().length,n,'invalid input must not inspect/change client');
   }
   assert.equal(existsSync(path.join(dir,'unused-home')),false,'no real client configuration created');
  }finally{rmSync(dir,{recursive:true,force:true});}
 });
}
