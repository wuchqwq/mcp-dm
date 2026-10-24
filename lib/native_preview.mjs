// Display adapter only. DM already selected native point values and produced
// the declared gray8 sampling. Encoding never alters scientific image objects.
import {deflateSync} from 'node:zlib';

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; ++bit) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const length = Buffer.alloc(4); length.writeUInt32BE(data.length);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}
export function encodeNativePreview(result) {
  const {width, height, gray8_hex: hex} = result ?? {};
  if (result?.backend !== 'digitalmicrograph-native' || result.operation !== 'PREVIEW' || result.quantitative !== false ||
      !Number.isInteger(result.image_id) || result.image_id < 0 || result.image_id > 0xffffffff ||
      !Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width > 128 || height > 128 ||
      result.sample_count !== width * height || typeof hex !== 'string' || hex.length !== width * height * 2 ||
      !/^[0-9a-f]+$/.test(hex)) throw new Error('Invalid bounded native gray8 preview contract');
  const pixels = Buffer.from(hex, 'hex');
  const rows = Buffer.alloc(height * (width + 1));
  for (let y = 0; y < height; ++y) pixels.copy(rows, y * (width + 1) + 1, y * width, (y + 1) * width);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // Bit depth 8, color type 0 (gray), no interlace.
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr), chunk('IDAT', deflateSync(rows)), chunk('IEND', Buffer.alloc(0))]);
}
export function nativePreviewImage(result) {
  return {type: 'image', mimeType: 'image/png', data: encodeNativePreview(result).toString('base64')};
}
