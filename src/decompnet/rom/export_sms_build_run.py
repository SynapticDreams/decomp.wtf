"""Standalone build orchestration, separate from the SMS/GG disassembly renderer."""
import hashlib
import shutil

from sms_identity import strip_copier_header, verify_normalized
from sms_export_report import Report
from sms_export_artifacts import read_regular


def build(module, argv):
    root, config, layout, out = module.ROOT, module.B, module.L, module.OUT
    report = Report(root, config, layout, argv)
    try:
        if set(argv) - {'--no-documented', '--require-documented'}:
            raise ValueError('unknown build option')
        image = root / config['image']
        if not image.exists():
            module.fail(f"put your own copy of the game here as {config['image']}")
        raw, info = read_regular(image, config['size'] + 513)
        if info.st_size > config['size'] + 512:
            raise ValueError('original input size differs')
        data = strip_copier_header(raw)
        if hashlib.sha1(data).hexdigest() != config['sha1']:
            module.fail(f"{config['image']} isn't the version this project is for (its sha1 differs)")
        verify_normalized(data, config.get('identity'), config['sha1'])
        report.input(data)
        report.value['process']['stage'] = 'tools'
        asm, link = module.tools()
        module.hardware()
        folder = out / 'disassembly'
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        print("disassembling your copy (with the project's names)")
        report.value['process']['stage'] = 'source'
        disassembly = module.Disassembly(data, documented='--no-documented' not in argv)
        disassembly.decode()
        disassembly.name_targets()
        disassembly.used_names()
        notes = module.comments()
        banks = [disassembly.bank(bank, notes) for bank in range(disassembly.banks)]
        left = {name for name, _ in disassembly.left}
        for entry in disassembly.documented.values():
            if entry['name'] not in left and not disassembly.done.get(entry['flat']):
                disassembly.left.append((entry['name'], 'its start falls inside what comes before it here'))
        report.sources(disassembly, disabled='--no-documented' in argv)
        for name, why in disassembly.left:
            print(f'left as bytes: {name}: {why}')
        names = (root / 'documented' / 'names.inc').read_text(encoding='utf-8') if (root / 'documented' / 'names.inc').exists() else ''
        names += ''.join(f'.DEFINE {name} ${value:04X}\n' for name, value in sorted(disassembly.defines.items()))
        (folder / 'names.inc').write_text(names, encoding='utf-8')
        shutil.copyfile(root / 'include' / 'hardware.inc', folder / 'hardware.inc')
        size = min(module.BANK, len(data))
        game = ['.MEMORYMAP', 'DEFAULTSLOT 0', 'SLOT 0 $0000 $4000', 'SLOT 1 $4000 $4000', 'SLOT 2 $8000 $4000', '.ENDME',
                '.ROMBANKMAP', f'BANKSTOTAL {disassembly.banks}', f'BANKSIZE ${size:04X}', f'BANKS {disassembly.banks}', '.ENDRO',
                '.INCLUDE "hardware.inc"', '.INCLUDE "names.inc"']
        for bank, text in enumerate(banks):
            (folder / f'bank_{bank:03d}.asm').write_text(text, encoding='utf-8')
            game.append(f'.INCLUDE "bank_{bank:03d}.asm"')
        (folder / 'game.asm').write_text('\n'.join(game) + '\n', encoding='utf-8')
        (folder / 'link.txt').write_text('[objects]\ngame.o\n', encoding='utf-8')
        print(f'{disassembly.placed} documented routines in place of their bytes')
        rom = f"game.{'gg' if config['platform'] == 'gg' else 'sms'}"
        report.value['process']['stage'] = 'assemble'
        module.run([asm, '-o', 'game.o', 'game.asm'], folder)
        report.value['process']['stage'] = 'link'
        module.run([link, '-S', '-r', 'link.txt', rom], folder)
        report.value['process']['stage'] = 'artifact'
        built = (folder / rom).read_bytes()
        shutil.copyfile(folder / rom, out / rom)
        result = report.complete(data, built)
        if built == data:
            print(f'identical: build/{rom} is your copy of the game, byte for byte')
        else:
            print(f"differs: build/{rom} first differs at ${report.value['image']['first_difference']:06x}")
        if report.value['documented']['required'] and any(not row['inserted'] for row in report.value['documented']['routines']):
            print('required documented source was omitted')
        return result
    except (Exception, SystemExit) as exc:
        report.value['process']['failure'] = type(exc).__name__
        for row in report.value['documented']['routines']:
            if not row['inserted'] and not row['omission']:
                row['omission'] = 'build_failed_at_' + report.value['process']['stage']
        print(str(exc), file=module.sys.stderr)
        return 1
    finally:
        report.write()
