"""The mandatory UI gate cannot pass on an omitted platform, skipped browser or stale report."""
import xml.etree.ElementTree as ET

import pytest

from tools import sms_ui_gate


def report(tmp_path, omit=None, tag=None):
    root = ET.Element('testsuite')
    for module, names in {**sms_ui_gate.REQUIRED, 'tests.test_sms_ui_gate': {'authored_verifier_case'}}.items():
        for name in names:
            if name == omit:
                continue
            case = ET.SubElement(root, 'testcase', classname=module, name=name)
            if tag:
                ET.SubElement(case, tag)
    path = tmp_path / 'ui-report.xml'
    ET.ElementTree(root).write(path)
    return path


@pytest.mark.parametrize('tag', ['skipped', 'failure', 'error'])
def test_ui_gate_refuses_skips_and_failures(tmp_path, tag):
    with pytest.raises(ValueError, match='zero skips'):
        sms_ui_gate.verify_report(report(tmp_path, tag=tag))


def test_ui_gate_requires_both_real_platform_workflows_and_tools(tmp_path, monkeypatch):
    assert sms_ui_gate.verify_report(report(tmp_path)) == 5
    with pytest.raises(ValueError, match='missing required'):
        sms_ui_gate.verify_report(report(tmp_path, omit=sms_ui_gate.LIVE + '[gg]'))
    with pytest.raises(ValueError, match='valid fresh'):
        sms_ui_gate.verify_report(tmp_path / 'absent.xml')
    monkeypatch.setattr(sms_ui_gate.shutil, 'which', lambda _name: None)
    with pytest.raises(ValueError, match='requires Chrome'):
        sms_ui_gate.require_tools()
