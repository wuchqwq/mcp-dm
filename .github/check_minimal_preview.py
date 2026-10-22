"""Validation-only smoke in a genuinely Matplotlib-free external venv."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import numpy as np

assert importlib.util.find_spec('matplotlib') is None, 'This check requires no Matplotlib'
root = Path(__file__).resolve().parents[1]
worker = root / 'tools' / 'analysis_worker.py'
with tempfile.TemporaryDirectory(prefix='dm_preview_scope_') as temp:
    folder = Path(temp)
    pixels = np.arange(24, dtype=np.float32).reshape(4, 6)
    with open(folder / 'input.npy', 'xb') as stream:
        np.save(stream, pixels, allow_pickle=False)
    digest = hashlib.sha256((folder / 'input.npy').read_bytes()).hexdigest()
    info = {'capture_id': 'synthetic-minimal-preview', 'shape_yx': [4, 6], 'dtype': 'float32',
            'source_shape_yx': [14, 16], 'source_rect_xyxy': [10, 10, 16, 14],
            'input_file': 'input.npy', 'input_sha256': digest}
    canonical = json.dumps(info, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    manifest = {'state': 'captured', 'capture_id': info['capture_id'], 'input_sha256': digest,
                'input_metadata_sha256': hashlib.sha256(canonical).hexdigest()}
    (folder / 'input.json').write_text(json.dumps(info), encoding='utf-8')
    (folder / 'capture.json').write_text(json.dumps(manifest), encoding='utf-8')
    for payload in ({'action': 'preview', 'capture_dir': temp, 'max_side': 32},
                    {'action': 'result', 'capture_dir': temp}):
        run = subprocess.run([sys.executable, '-B', str(worker)], input=json.dumps(payload),
                             text=True, capture_output=True, timeout=60)
        assert run.returncode == 0, run.stderr + run.stdout
        result = json.loads(run.stdout)
        assert result['ok'], result
        print(payload['action'], result['result']['state'], 'PASS without Matplotlib')
