"""Browser JSON editing follows the existing bounded backend codec, including duplicate keys."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from decompnet.rom.annotations.codec import load


def test_research_editor_json_agrees_with_backend_codec_for_exact_and_invalid_values():
    node = shutil.which('node')
    if node is None:
        pytest.skip('requires Node for the browser JSON parser')
    values = ['null', 'true', '-0', str(2**53 - 1), str(-(2**53 - 1)),
              '{"flags":[1,false,null],"nested":{"label":"\\nUnicode: é"}}',
              '{"__proto__":{"authored":true},"constructor":1}', ' [1,2] \r\n',
              json.dumps('😀' * 4096, ensure_ascii=False), json.dumps('😀' * 4097, ensure_ascii=False),
              json.dumps({'😀' * 128: 0}, ensure_ascii=False), json.dumps({'😀' * 129: 0}, ensure_ascii=False),
              '{"kind":"data","kind":"code"}', '{"a":1,"\\u0061":2}', '{"x":{"a":1,"a":2}}',
              '1.0', '1e0', str(2**53), 'NaN', 'Infinity', '01', '1x', '[1,]', '{"a":1,}',
              '"\\u0000"', json.dumps('a' * 4097), json.dumps({'k' * 129: 1}),
              '[' * 17 + '0' + ']' * 17, json.dumps([0] * 4096), json.dumps(['é' * 4000] * 16, ensure_ascii=False),
              '\u00a0null', '', '{"a": [1,2}', '"unterminated', 'true false']
    script = Path(__file__).resolve().parents[1] / 'src/decompnet/app/static/research-json.js'
    command = '''const fs = require('node:fs'); global.window = {};
require(process.argv[1]);
const rows = JSON.parse(fs.readFileSync(0, 'utf8')).map(raw => {
  try { return {ok: true, value: window.ResearchJSON.parse(raw)}; }
  catch (_) { return {ok: false}; }
}); process.stdout.write(JSON.stringify(rows));'''
    result = subprocess.run([node, '-e', command, str(script)], input=json.dumps(values), capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    outputs = json.loads(result.stdout)
    for raw, actual in zip(values, outputs, strict=True):
        try:
            expected = {'ok': True, 'value': load(raw)}
        except (ValueError, TypeError, RecursionError):
            expected = {'ok': False}
        assert actual == expected, raw[:100]
