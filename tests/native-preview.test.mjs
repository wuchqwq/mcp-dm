import test from 'node:test';
import assert from 'node:assert/strict';
import {inflateSync} from 'node:zlib';
import {encodeNativePreview, nativePreviewImage} from '../lib/native_preview.mjs';

const image = {backend: 'digitalmicrograph-native', operation: 'PREVIEW', image_id: 17,
  width: 3, height: 2, sample_count: 6, gray8_hex: '00204080c0ff', quantitative: false};
test('native preview PNG independently decodes to the exact DM gray8 rows without transpose', () => {
  const png = encodeNativePreview(image);
  assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  const chunks = [];
  for (let pos = 8; pos < png.length;) {
    const length = png.readUInt32BE(pos);
    chunks.push({name: png.toString('ascii', pos + 4, pos + 8), data: png.subarray(pos + 8, pos + 8 + length)});
    pos += 12 + length;
    assert.ok(pos <= png.length);
  }
  assert.deepEqual(chunks.map(chunk => chunk.name), ['IHDR', 'IDAT', 'IEND']);
  assert.deepEqual([...chunks[0].data], [0, 0, 0, 3, 0, 0, 0, 2, 8, 0, 0, 0, 0]);
  assert.deepEqual([...inflateSync(chunks[1].data)], [0, 0, 32, 64, 0, 128, 192, 255]);
  assert.equal(png.subarray(-4).toString('hex'), 'ae426082'); // Known standard IEND CRC.
  assert.equal(nativePreviewImage(image).data, png.toString('base64'));
});
test('PNG adapter refuses malformed/oversized pixels, scientific substitution and wrong backend', () => {
  for (const fault of [{width: 129}, {height: 0}, {sample_count: 5}, {gray8_hex: 'ff'},
    {gray8_hex: 'gg204080c0ff'}, {image_id: true}, {quantitative: true}, {operation: 'FFT'}, {backend: 'python'}]) {
    assert.throws(() => encodeNativePreview({...image, ...fault}), /Invalid bounded native/);
  }
});
