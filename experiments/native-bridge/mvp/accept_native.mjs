#!/usr/bin/env node
// Explicit real-host acceptance; never starts/stops DM or retries an operation.
import assert from "node:assert/strict";
import {readFileSync, writeFileSync} from "node:fs";
import {NativeBridge} from "../../../lib/native_bridge.mjs";
const [fixtureFile, outputFile, phase = "mean"] = process.argv.slice(2);
if (!fixtureFile || !outputFile || !["info", "datasets", "mean"].includes(phase)) {
  throw new Error("Usage: node accept_native.mjs PRIVATE_FIXTURE_JSON NEW_RESULT_JSON info|datasets|mean");
}
const fixture = JSON.parse(readFileSync(fixtureFile, "utf8"));
assert.equal(fixture.session, process.env.DM_NATIVE_SESSION);
const bridge = new NativeBridge({session: fixture.session, timeoutMs: 5000});
const receipts = [];
async function call(op, args, id) {
  const receipt = await bridge.execute(op, args, {requestId: id});
  receipts.push(receipt);
  assert.equal(receipt.state, "completed", JSON.stringify(receipt));
  assert.equal(receipt.result.backend, "digitalmicrograph-native");
  return receipt.result;
}
try {
  const status = await call("STATUS", [], phase + "_status");
  assert.equal(status.ready, true);
  assert.equal(status.binary_gate, true);
  assert.equal(status.resident_python_required, false);
  if (phase === "info") {
    for (const source of fixture.images) {
      const info = await call("INFO", [source.id], "info_" + source.id);
      assert.equal(info.image_id, source.id);
      assert.equal(info.ndim, 2);
      assert.equal(info.data_type_code, 2);
      assert.deepEqual(info.dm_dimensions, [...source.shape].reverse());
    }
  } else if (phase === "datasets") {
    const result = await call("DATASETS", [], "datasets_metadata");
    for (const source of fixture.images) {
      const info = result.datasets.find(image => image.id === source.id);
      assert.ok(info);
      assert.equal(info.name, source.name);
      assert.equal(info.dtype, source.dtype);
      assert.deepEqual(info.shape, source.shape);
      for (const expected of source.calibration) {
        const axis = info.calibration.find(a => a.dm_dimension === expected.dm_axis);
        assert.equal(axis.calibrated_value_at_pixel_zero, expected.origin);
        assert.equal(axis.scale, expected.scale);
        assert.equal(axis.unit, expected.unit);
      }
    }
  } else {
    for (const source of fixture.images) {
      for (let i = 0; i < 12; ++i) {
        const result = await call("MEAN", [source.id], "mean_" + source.id + "_" + i);
        assert.equal(result.image_id, source.id);
        assert.equal(result.mean, source.mean); // Exact binary-fraction fixture.
        assert.equal(result.operator, "GMSImageProcessing::GetMean");
        assert.equal(result.intensity_calibration_applied, false);
      }
    }
    const missing = await bridge.execute("INFO", [0xffffffff], {requestId: "invalid_image"});
    receipts.push(missing);
    assert.equal(missing.state, "failed");
    assert.match(missing.error, /image_not_found/);
  }
  writeFileSync(outputFile, JSON.stringify({status: "PASS", phase, receipts}, null, 2), {flag: "wx"});
  console.log("PASS " + phase + "; " + receipts.length + " native operation receipts");
} catch (error) {
  writeFileSync(outputFile, JSON.stringify({status: "FAIL", phase, error: String(error), receipts}, null, 2), {flag: "wx"});
  throw error;
} finally { bridge.close(); }
