// Repository Skill packaging/contracts only. No Skill install, model evaluation,
// scientific calculation, DM or browser qualification is implied.
import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync, readdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServerRuntime} from '../lib/tools/create_server_runtime.mjs';
import {validate} from '../lib/runtime/schema.mjs';
import {ToolRegistry} from '../lib/runtime/tool_registry.mjs';
import {createAnalysisContextModule} from '../lib/tools/analysis_context_module.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const skills = path.join(root, 'skills', 'scientific-agent');
const contractFolder = path.join(tmpdir(), 'skill-contract-only-' + process.pid);
const values = Object.fromEntries(['TIFF_PATH', 'CIF_PATH', 'MEASUREMENT_PATH', 'NEW_EXPORT_PATH'].map(name => [name,
  path.join(contractFolder, name.toLowerCase() + (name === 'TIFF_PATH' ? '.tiff' : name === 'CIF_PATH' ? '.cif' : name === 'MEASUREMENT_PATH' ? '.json' : ''))]));
const runtime = createServerRuntime({env: {DM_MCP_BACKEND: 'images', DM_IMAGE_WORKSPACE: path.join(contractFolder, 'images'),
  DM_STRUCTURE_WORKSPACE: path.join(contractFolder, 'structures'), DM_MCP_EXECUTION_OBSERVABILITY: '1'}});
const definitions = new Map(runtime.registry.listTools().map(value => [value.name, value]));
const contextRegistry = new ToolRegistry().register(createAnalysisContextModule({directory: path.join(contractFolder, 'contexts'), providers: runtime.providers})).seal();
for (const definition of contextRegistry.listTools()) {assert.equal(definitions.has(definition.name), false); definitions.set(definition.name, definition);}
contextRegistry.close();
runtime.close();
function substitute(value) {
  if (typeof value === 'string') return value.replace(/\$\{([A-Z_]+)\}/g, (_, key) => {assert.ok(Object.hasOwn(values, key), 'unknown example parameter ' + key); return values[key];});
  if (Array.isArray(value)) return value.map(substitute);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, substitute(item)]));
  return value;
}
function matchesBranch(value, schema) {
  if (schema.required?.some(key => !Object.hasOwn(value, key))) return false;
  if (schema.not && matchesBranch(value, schema.not)) return false;
  if (schema.allOf && !schema.allOf.every(branch => matchesBranch(value, branch))) return false;
  if (schema.anyOf && !schema.anyOf.some(branch => matchesBranch(value, branch))) return false;
  if (schema.oneOf && schema.oneOf.filter(branch => matchesBranch(value, branch)).length !== 1) return false;
  return true;
}
function validateCall(name, args) {
  const tool = definitions.get(name); assert.ok(tool, 'actual enabled catalog is missing tool ' + name);
  validate(args, tool.inputSchema);
  assert.ok(matchesBranch(args, tool.inputSchema), 'example violates schema mutually exclusive fields for ' + name);
}

for (const folder of readdirSync(skills, {withFileTypes: true}).filter(entry => entry.isDirectory()).map(entry => entry.name)) {
  test('Skill references and example parameters match current registered tools: ' + folder, () => {
    const directory = path.join(skills, folder), filename = path.join(directory, 'SKILL.md');
    const content = readFileSync(filename, 'utf8');
    const frontmatter = content.match(/^---\r?\n([\s\S]*?)\r?\n---/); assert.ok(frontmatter, 'required YAML frontmatter');
    assert.match(frontmatter[1], new RegExp('(?:^|\\n)name: ' + folder + '(?:\\r?\\n|$)'));
    assert.match(frontmatter[1], /(?:^|\n)description: .+/);
    const fixture = JSON.parse(readFileSync(path.join(directory, 'examples.json'), 'utf8'));
    assert.equal(fixture.schema_version, 1); assert.equal(fixture.skill, folder);
    assert.ok(fixture.tool_refs.length > 0); assert.equal(new Set(fixture.tool_refs).size, fixture.tool_refs.length);
    for (const name of fixture.tool_refs) assert.ok(definitions.has(name), name + ' must be an actual enabled tool');
    for (const match of content.matchAll(/`((?:image|structure|execution|analysis|dm)_[a-z0-9_]+)`/g)) {
      assert.ok(definitions.has(match[1]), 'Skill prose references a missing tool: ' + match[1]);
      assert.ok(fixture.tool_refs.includes(match[1]), 'exact prose tool must be declared in the example manifest: ' + match[1]);
    }
    for (const match of content.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)) {
      assert.equal(existsSync(path.resolve(directory, match[1])), true, 'discoverable local Skill reference ' + match[1]);
    }
    const requestIds = new Set();
    for (const scenario of fixture.scenarios) {
      assert.ok(typeof scenario.intent === 'string' && scenario.intent.length);
      assert.ok(scenario.calls.length);
      for (const call of scenario.calls) {
        assert.ok(fixture.tool_refs.includes(call.tool));
        const args = substitute(call.arguments); validateCall(call.tool, args);
        if (definitions.get(call.tool).inputSchema.required?.includes('request_id')) {
          assert.ok(!requestIds.has(args.request_id), 'example writes use distinct pre-saved request IDs'); requestIds.add(args.request_id);
        }
      }
    }
    assert.equal(existsSync(contractFolder), false, 'contract validation does not execute a worker or create data');
  });
}

test('Skill example checker rejects actual invalid tool/schema/oneOf cases', () => {
  assert.throws(() => validateCall('structure_magic_pipeline', {}), /missing tool/);
  assert.throws(() => validateCall('image_fft', {object_id: 'a'.repeat(32)}), /request_id/);
  assert.throws(() => validateCall('image_frame', {object_id: 'a'.repeat(32), frame_index: -1, request_id: 'bad-frame'}));
  assert.throws(() => validateCall('structure_simulate', {object_id: 'a'.repeat(32), orientation_id: 'b'.repeat(32), euler_rzxz_deg: [0, 0, 0],
    voltage_kv: 200, reciprocal_radius_inv_angstrom: 1, max_excitation_error_inv_angstrom: 0.02, request_id: 'bad-two-orientations'}), /mutually exclusive/);
});

test('Context examples require CAS identity and reject ambiguous historical/recovery targets', async () => {
  assert.throws(() => validateCall('analysis_update', {analysis_id: 'example-analysis', request_id: 'missing-base', reason: 'Invalid example', selections: {}}), /expected_revision/);
  assert.throws(() => validateCall('analysis_update', {analysis_id: 'example-analysis', expected_revision: 1, request_id: 'invalid-provider', reason: 'Invalid example',
    selections: {experiment: {provider: 'native', object_id: 'a'.repeat(32)}}}));
  await assert.rejects(contextRegistry.call('analysis_read', {analysis_id: 'example-analysis', revision: 1, request_id: 'original-mutation'}), /Choose revision or original context request_id/);
  assert.equal(existsSync(contractFolder), false, 'invalid selection/recovery examples never touch scientific or Context storage');
});
