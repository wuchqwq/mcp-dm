// Source-reviewed call shapes only: this neither launches nor contacts MP.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {structureTools} from '../lib/structure_workspace.mjs';
import {validate} from '../lib/runtime/schema.mjs';

const directory = fileURLToPath(new URL('../skills/materials-project-reference/', import.meta.url));
const fixture = JSON.parse(readFileSync(path.join(directory, 'examples.json'), 'utf8'));

test('Optional MP Skill keeps official-provider examples separate from local science tools', () => {
  assert.equal(fixture.contract.evidence, 'upstream_source_review_not_live_catalog');
  assert.match(fixture.contract.source, /materialsproject\/api\/blob\/[a-f0-9]{40}\/mp_api\/mcp\/tools\.py$/);
  assert.equal(fixture.candidate_status, 'hypothesized');
  assert.equal(fixture.official_calls[0].tool, 'search');
  for (const call of fixture.official_calls) {
    validate(call.arguments, fixture.contract.tools[call.tool]);
    if (call.tool === 'fetch') assert.match(call.arguments.idx, /^mp-[0-9]+$/);
  }
  assert.throws(() => validate({query: 'Ti-O'}, fixture.contract.tools.fetch), /idx/);
  const tools = new Map(structureTools.map(tool => [tool.name, tool]));
  const requests = new Set();
  for (const call of fixture.local_calls) {
    const args = {...call.arguments};
    if (args.source_path) args.source_path = path.resolve(directory, 'example-only.cif');
    validate(args, tools.get(call.tool).inputSchema);
    assert.equal(requests.has(args.request_id), false); requests.add(args.request_id);
  }
  assert.equal(existsSync(path.join(directory, 'example-only.cif')), false);
});

test('MP Skill local resources and setup guide are discoverable without installing a provider', () => {
  const content = readFileSync(path.join(directory, 'SKILL.md'), 'utf8');
  assert.match(content, /^---\r?\nname: materials-project-reference\r?\n/);
  for (const match of content.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)) {
    assert.equal(existsSync(path.resolve(directory, match[1])), true, 'missing Skill reference ' + match[1]);
  }
  assert.equal(structureTools.some(tool => tool.name === 'search' || tool.name === 'fetch'), false);
});
