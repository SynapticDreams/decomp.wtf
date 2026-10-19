/* Mechanical outcomes are not percentages or semantic approval. */
(() => {
  try {
    const assert = (x, why) => { if (!x) throw new Error(why); };
    const panel = document.getElementById('panel');
    const detail = { assembly_work: { deferred: true, reason: '<img src=x> pending mapping', validation: {
      current: true, byte_identical: true, target: 20, same: 20, assembled: 20,
      checks: [{ label: 'Byte equality', state: 'passed', problems: [] },
        { label: 'ROM mapping', state: 'pending', problems: ['<img src=x> unresolved target'] },
        { label: 'Hardware names', state: 'not_checked', problems: [] }] } } };
    window.AssemblyWorkUI.render(panel, detail);
    assert(panel.textContent.includes('Bytes identical: 20 / 20'), 'byte equality has its own result');
    assert(panel.textContent.includes('Pending evidence') && panel.textContent.includes('Not checked'), 'unknown checks never become success');
    assert(panel.textContent.includes('Documentation deferred') && panel.textContent.includes('Helpers skip'), 'blocked work explains eligibility');
    assert(!panel.querySelector('img') && panel.textContent.includes('<img src=x>'), 'agent text is rendered literally');
    detail.assembly_work.validation.current = false;
    detail.assembly_work.deferred = false;
    detail.assembly_work.evidence_changed = true;
    window.AssemblyWorkUI.render(panel, detail);
    assert(panel.textContent.includes('Previous context') && panel.textContent.includes('eligible for another check'), 'stale receipts are qualified');
    window.AssemblyWorkUI.render(panel, {});
    assert(panel.hidden && !panel.childNodes.length, 'switching to C clears the assembly panel');
    document.getElementById('report').textContent = 'PASS: separate checks, deferred evidence, stale receipts and escaped text';
  } catch (e) { document.getElementById('report').textContent = 'FAIL: ' + e.stack; }
})();
