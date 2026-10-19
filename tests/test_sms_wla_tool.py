"""Actual pinned WLA output qualifies nonuniform source geometry for SMS/GG discovery."""
import subprocess

import pytest

from decompnet.rom import sms, sms_asm, sms_trace, wla_layout, wla_symbols
from .sms_wla_fixture import SOURCE, layout_for


@pytest.mark.skipif(not sms_asm.available(), reason='needs pinned WLA-DX')
@pytest.mark.parametrize('platform', ['sms', 'gg'])
def test_actual_nonuniform_wla_symbols_seed_the_right_bytes_and_keep_aliases(tmp_path, platform):
    assembler, linker = sms_asm._tools()
    (tmp_path / 'game.asm').write_text(SOURCE)
    (tmp_path / 'link').write_text('[objects]\ngame.o\n')
    for args in ([str(assembler), '-i', '-o', 'game.o', 'game.asm'],
                 [str(linker), '-S', '-A', 'link', f'game.{platform}']):
        run = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stdout + run.stderr
    path = tmp_path / f'game.{platform}'
    image = path.read_bytes()
    original = path.with_suffix('.sym').read_bytes()
    imported = wla_symbols.normalize(wla_symbols.read(original), wla_layout.declare(layout_for(image), image), image)
    assert imported.document.version == 3 and imported.document.rom_crc32
    assert imported.aliases[(0, 0x2100)] == ['First', 'FirstAlias']
    assert imported.names[(0, 0x1100)] == 'MainAt1100'
    assert imported.names[(2, 0x1100)] == 'OtherAt1100'
    with pytest.raises(ValueError, match='need layout/image'):
        sms_trace.read_sym(original.decode())
    assert sms_trace.read_sym(original.decode(), layout=layout_for(image), image=image)[(0, 0x2100)] == 'First'
    report = {}
    functions = {f.rom: f for f in sms.split(path, tmp_path, report=report, symbol_layout=layout_for(image))}
    for flat, cpu, name, code in ((0x2100, 0x2100, 'First', '3e01c9'), (0x6100, 0x6100, 'Second', '3e02c9'),
                                  (0x8100, 0x8100, 'Third', '3e03c9'), (0x9000, 0x1000, 'Paged', '3e07c9'),
                                  (0x1100, 0x1100, 'MainAt1100', '3e04c9'), (0x9100, 0x1100, 'OtherAt1100', '3e08c9')):
        assert functions[flat].vram == cpu and functions[flat].name == name
        assert functions[flat].code == bytes.fromhex(code)
    assert functions[0x2300].name == 'func_000_2300'
    assert 0x2200 not in functions and 0x2400 not in functions  # plausible bytes in data/unknown views are not symbol seeds
    assert not any(f.name.startswith('_LABEL_') or f.name == 'wState' for f in functions.values())
    assert path.with_suffix('.sym').read_bytes() == original
    assert report['symbol_import']['source']['sha256'] == imported.document.sha256
    assert any(row['name'] == 'FirstAlias' for row in report['symbol_import']['records'])
    with pytest.raises(ValueError, match='different normalized input'):
        sms.split(path, tmp_path, symbol_layout={**layout_for(image), 'input': {'size': len(image), 'sha256': '0' * 64}})
