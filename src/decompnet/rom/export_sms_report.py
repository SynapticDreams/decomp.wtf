"""Standalone SMS/GG build receipts. Copied into exported tools; no application dependencies."""
import hashlib
import json


def identity(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def source_digest(text):
    return hashlib.sha256(text.replace('\r\n', '\n').replace('\r', '\n').strip().encode()).hexdigest()


class Report:
    def __init__(self, root, config, layout, argv):
        self.root, self.config = root, config
        self.expected = config.get('expected_documented', layout.get('documented', []))
        normalized = (config.get('identity') or {}).get('normalized') if isinstance(config.get('identity'), dict) else None
        self.value = {'version': 1, 'passed': False, 'input': {'verified': False, 'expected_sha1': config.get('sha1'),
                                                           'expected_normalized': normalized},
                      'image': {'equal': False}, 'process': {'completed': False, 'stage': 'input', 'exit_code': 1},
                      'documented': {'required': '--require-documented' in argv, 'routines': [],
                                     'source_hash_scope': 'UTF-8 text with universal newlines and stripped edge whitespace'},
                      'c_reference': config.get('c_reference', {'verified_by_build': False, 'source_linked': False}),
                      'typed_data': {'status': 'not_evaluated'}, 'semantic_review': {'status': 'not_evaluated'},
                      'runtime_parity': {'status': 'not_tested'}}
        self.value['documented']['routines'] = [
            {key: entry.get(key) for key in ('name', 'flat', 'cpu', 'size', 'source_sha256')} |
            {'emitted': False, 'inserted': False, 'omission': entry.get('omission') or 'build_not_completed'}
            for entry in self.expected]
        self.path = root / 'build' / 'verification.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.unlink(missing_ok=True)
        platform = 'gg' if config.get('platform') == 'gg' else 'sms'
        (root / 'build' / f'game.{platform}').unlink(missing_ok=True)

    def input(self, data):
        self.value['input'].update(verified=True, normalized=identity(data))

    def sources(self, disassembly, disabled=False):
        omitted = dict(disassembly.left)
        rows = []
        for entry in self.expected:
            selected = disassembly.documented.get(entry['flat'])
            emitted = bool(selected and selected['name'] == entry['name'] and disassembly.done.get(entry['flat']))
            reason = ('disabled_by_option' if disabled else omitted.get(entry['name']) or entry.get('omission') or
                      'documented_source_not_emitted') if not emitted else None
            rows.append({key: entry.get(key) for key in ('name', 'flat', 'cpu', 'size', 'source_sha256')} |
                        {'emitted': emitted, 'inserted': False, 'omission': reason,
                         'actual_source_sha256': disassembly.source_hashes.get(entry['flat']) if emitted else None})
        self.value['documented']['routines'] = rows

    def complete(self, original, built):
        self.value['process']['completed'] = True
        self.value['image'] = {'equal': built == original, 'original': identity(original), 'built': identity(built),
                               'first_difference': next((i for i, (a, b) in enumerate(zip(original, built)) if a != b),
                                                        min(len(original), len(built))) if built != original else None}
        for row in self.value['documented']['routines']:
            row['inserted'] = row['emitted']
        omitted = any(not row['inserted'] for row in self.value['documented']['routines'])
        passed = built == original and not (self.value['documented']['required'] and omitted)
        self.value['passed'] = passed
        self.value['process'].update(stage='complete', exit_code=0 if passed else 1)
        return 0 if passed else 1

    def write(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.value, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        temporary.replace(self.path)
