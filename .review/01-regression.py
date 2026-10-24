from pathlib import Path
p=Path.cwd()/'tests/native-region-handoff.test.mjs'
s=p.read_text()
s+='''
for (const unsigned of [false, true]) test(`independent directories with the same export name read fresh ${unsigned ? 'uint32' : 'float32'} pixels`, async t => {
  const firstDir = temp(t), secondDir = temp(t);
  let epoch = 1, executions = 0;
  const f = fixture({unsigned, mutate: reply => {
    if (reply.original_operation !== 'READ') return;
    const bytes = Buffer.from(reply.result.values_base64, 'base64');
    for (let i = 0; i < bytes.length; i += 4) {
      if (unsigned) bytes.writeUInt32LE(16777216 + epoch, i);
      else bytes.writeFloatLE(epoch + 0.25, i);
    }
    reply.result.values_base64 = bytes.toString('base64');
  }});
  // Emulate the production core's immutable same-session deduplication, not
  // an echo peer which incorrectly executes every repeated READ afresh.
  f.bridge.execute = async (op, args, {requestId}) => {
    f.calls.push([op, requestId, args]);
    if (!f.saved.has(requestId)) {
      const reply = f.response(op, args, requestId);
      f.saved.set(requestId, reply);
      if (op === 'READ') ++executions;
    }
    return f.saved.get(requestId);
  };
  const first = await handoffRegion(opts(firstDir), () => f.bridge);
  const firstFile = path.join(firstDir, 'capture', 'input.npy');
  const firstBytes = fs.readFileSync(firstFile);
  epoch = 2; // Editing BETWEEN completed exports, never during a capture.
  const second = await handoffRegion(opts(secondDir), () => f.bridge);
  const secondBytes = fs.readFileSync(path.join(secondDir, 'capture', 'input.npy'));
  assert.equal(first.state, 'captured'); assert.equal(second.state, 'captured');
  assert.equal(executions, 10, 'both independent exports must execute all five READs');
  assert.notDeepEqual(firstBytes, secondBytes, 'the new directory must not receive a cached old capture');
  assert.deepEqual(fs.readFileSync(firstFile), firstBytes, 'the old capture remains immutable');
  const value = bytes => unsigned ? bytes.readUInt32LE(bytes.length - 4) : bytes.readFloatLE(bytes.length - 4);
  assert.equal(value(firstBytes), unsigned ? 16777217 : 1.25);
  assert.equal(value(secondBytes), unsigned ? 16777218 : 2.25);
  const calls = f.calls.length;
  assert.deepEqual(await handoffRegion(opts(firstDir), () => { throw Error('reuse must be offline'); }), first);
  assert.deepEqual(await handoffRegion(opts(secondDir), () => { throw Error('reuse must be offline'); }), second);
  assert.equal(f.calls.length, calls);
});
'''
p.write_text(s)
