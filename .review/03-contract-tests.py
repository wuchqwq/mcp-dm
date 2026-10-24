from pathlib import Path
root=Path.cwd()
p=root/'tools/native_region_handoff.mjs';s=p.read_text().replace("typeof options.captureId==='string'&&/", "typeof options.captureId==='string'&&options.captureId.length===32&&/").replace("typeof journal.capture_id==='string'&&/", "typeof journal.capture_id==='string'&&journal.capture_id.length===32&&/");p.write_text(s)
p=root/'tests/native-region-handoff.test.mjs';s=p.read_text();s+='''
const journalPath = dir => path.join(dir, fs.readdirSync(dir).find(name => name.startsWith('.native-region-') && name.endsWith('.json')));
const saveJson = (filename, value) => fs.writeFileSync(filename, JSON.stringify(value, null, 2) + '\\n');
const shaBytes = value => createHash('sha256').update(value).digest('hex');

test('wire plans are deterministic only within one persisted capture identity', () => {
  const args = {...opts('unused'), captureId: 'a'.repeat(32)};
  const first = planRegion(args), same = planRegion(args), next = planRegion({...args, captureId: 'c'.repeat(32)});
  assert.deepEqual(first, same);
  const ids = p => [p.status.request.id, ...p.blocks.map(block => block.request.id)];
  assert.ok(ids(first).every(id => !ids(next).includes(id) && /^[A-Za-z0-9_-]{1,64}$/.test(id)));
  for (const captureId of [undefined, null, '', true, 'A'.repeat(32), 'a'.repeat(32) + '\\n'])
    assert.throws(() => planRegion({...args, captureId}), /capture ID/);
});

test('capture namespace is durable before dispatch and is reused on explicit recovery', async t => {
  const dir = temp(t), f = fixture(); let interrupt = true, original;
  const execute = f.bridge.execute;
  f.bridge.execute = async (...args) => {
    const reply = await execute(...args);
    if (args[0] === 'READ' && interrupt) { interrupt = false; throw Error('accepted then disconnected'); }
    return reply;
  };
  await assert.rejects(() => handoffRegion(opts(dir), () => {
    original = readJson(journalPath(dir));
    assert.equal(original.request_namespace_version, 2);
    assert.equal(original.workspace_realpath, fs.realpathSync(dir));
    assert.deepEqual(original.plan, planRegion({...opts(dir), captureId: original.capture_id}));
    assert.equal(f.calls.length, 0);
    return f.bridge;
  }), /disconnected/);
  await handoffRegion({...opts(dir), recover: true}, () => f.bridge);
  const restored = readJson(journalPath(dir));
  assert.equal(restored.capture_id, original.capture_id);
  assert.deepEqual(restored.plan, original.plan);
  assert.equal(f.calls.filter(([op]) => op === 'READ').length, 5, 'no accepted READ resubmitted');
});

test('copied partial journals fail before connecting or changing existing evidence', async t => {
  const dir = temp(t), f = fixture();
  const execute = f.bridge.execute;
  f.bridge.execute = async (...args) => { const r = await execute(...args); if (args[0] === 'READ') throw Error('disconnect'); return r; };
  await assert.rejects(() => handoffRegion(opts(dir), () => f.bridge), /disconnect/);
  const copy = temp(t); fs.cpSync(dir, copy, {recursive: true});
  const filename = journalPath(copy), before = fs.readFileSync(filename);
  await assert.rejects(() => handoffRegion({...opts(copy), recover: true}, () => { throw Error('must not connect'); }), /another output directory/);
  assert.deepEqual(fs.readFileSync(filename), before);
  assert.equal(fs.readdirSync(copy).some(name => name.endsWith('.lock')), false);
});

test('changed capture namespace and STATUS request fail before native calls', async t => {
  const dir = temp(t), f = fixture(); await handoffRegion(opts(dir), () => f.bridge);
  const filename = journalPath(dir), original = readJson(filename);
  for (const mutate of [
    j => { j.capture_id = 'c'.repeat(32); },
    j => { j.capture_id += '\\n'; },
    j => { j.request_namespace_version = 99; },
    j => { j.status.request.id = 'another-status'; },
  ]) {
    const changed = structuredClone(original); mutate(changed); saveJson(filename, changed);
    const before = fs.readFileSync(filename);
    await assert.rejects(() => handoffRegion({...opts(dir), recover: true}, () => { throw Error('must not connect'); }), /identity|namespace|plan/);
    assert.deepEqual(fs.readFileSync(filename), before);
  }
  saveJson(filename, original);
});

// Construct a saved legacy fixture by rewriting only wire identities and all
// dependent hashes. No legacy producer/recovery path is enabled in production.
function convertCompletedToLegacy(dir) {
  const file = journalPath(dir); let journal = readJson(file);
  const p = journal.parameters;
  const oldPrefix = 'region-' + shaBytes(canonical({imageId:p.imageId, rect:p.rect, blockSamples:p.blockSamples,
    session:p.session, hostPid:p.hostPid, requestId:p.requestId})).slice(0,32);
  const prefix = journal.plan.status.request.id.slice(0, -7);
  const remap = value => JSON.parse(JSON.stringify(value).replaceAll(prefix, oldPrefix));
  journal = remap(journal);
  delete journal.request_namespace_version; delete journal.workspace_realpath;
  const target = path.join(dir, p.output);
  let info = remap(readJson(path.join(target,'input.json'))), manifest = remap(readJson(path.join(target,'capture.json')));
  for (let i=0;i<journal.blocks.length;++i) {
    const name = path.join(target, `read-${i}.json`);
    saveJson(name, remap(readJson(name)));
    const digest = hashFile(name);
    journal.blocks[i].snapshot_sha256 = digest; info.native_receipts[i].snapshot_sha256 = digest;
  }
  manifest.blocks = structuredClone(journal.blocks);
  saveJson(path.join(target,'input.json'), info);
  manifest.input_metadata_sha256 = shaBytes(canonical(info));
  saveJson(path.join(target,'capture.json'), manifest);
  for(const name of ['input.npy','input.json','capture.json']) journal.capture_receipt.files_sha256[name]=hashFile(path.join(target,name));
  saveJson(file, journal);
  return {file, journal};
}

test('completed legacy journals remain verifiable offline, without claiming new isolated reads', async t => {
  const dir=temp(t),f=fixture(); await handoffRegion(opts(dir),()=>f.bridge);
  const {file}=convertCompletedToLegacy(dir),before=fs.readFileSync(file);
  const result=await handoffRegion({...opts(dir),recover:true},()=>{throw Error('legacy never connects');});
  assert.equal(result.state,'captured');
  assert.equal(result.request_namespace_status,'legacy_unscoped_saved_evidence_only');
  assert.deepEqual(fs.readFileSync(file),before);
  assert.equal(JSON.parse(execFileSync('python',['tools/verify_native_region.py','--capture',path.join(dir,'capture')],{encoding:'utf8'})).status,'PASS_INDEPENDENT_CHUNKED_FILES');
});

test('incomplete legacy journals are not silently migrated or recovered with colliding IDs', async t => {
  const dir=temp(t),f=fixture(); await handoffRegion(opts(dir),()=>f.bridge);
  const {file,journal}=convertCompletedToLegacy(dir);journal.state='PARTIAL';saveJson(file,journal);
  const before=fs.readFileSync(file);
  for(const recover of [false,true]) await assert.rejects(()=>handoffRegion({...opts(dir),recover},()=>{throw Error('legacy never connects');}),/LEGACY_REGION_RECOVERY_UNSAFE/);
  assert.deepEqual(fs.readFileSync(file),before);
});
''';p.write_text(s)
p=root/'tests/native-mcp.test.mjs';s=p.read_text();a='    assert.deepEqual({...first, native_receipt: undefined}, {...result, native_receipt: undefined}, "host fields stay unchanged without invented delivery claims");';b='''    const {display_context, ...nativeFields} = first;
    assert.deepEqual({...nativeFields, native_receipt: undefined}, {...result, native_receipt: undefined}, "host fields stay unchanged without invented delivery claims");
    assert.deepEqual(display_context, {scope: "document_delivery_only", active_workspace_visibility: "unknown",
      workspace_activation_requested: false, model_visual_verification: false, observation: "not_performed_by_mcp"});
    assert.equal(Object.hasOwn(result, "display_context"), false, "stored host result is not rewritten");''';assert a in s;s=s.replace(a,b,1)
s=s.replace('    assert.equal(output.native_receipt.request_id, request_id);','    assert.equal(Object.hasOwn(output, "display_context"), false, "non-SHOW outputs do not claim delivery");\n      assert.equal(output.native_receipt.request_id, request_id);',1)
s=s.replace('    const text = toolOutput(shown); assert.equal(text.image.dtype, "uint32"); assert.equal(text.file_saved, false);','    const text = toolOutput(shown); assert.equal(text.image.dtype, "uint32"); assert.equal(text.file_saved, false);\n    assert.equal(text.display_context.active_workspace_visibility, "unknown");\n    assert.equal(text.display_context.workspace_activation_requested, false);',1)
p.write_text(s)
