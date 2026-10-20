/* AI advice has explicit uncertainty and history; no untrusted HTML is executed. */
(() => {
  try {
    const assert = (x, why) => { if (!x) throw new Error(why); };
    const panel = document.getElementById('panel');
    const detail = { status: 'documented', sample: true, documentation_reviews: [] };
    window.AssemblyWorkUI.renderReview(panel, detail, true);
    assert(panel.textContent.includes('Review in progress') && panel.textContent.includes('leave this flag'), 'running and human review are clear');
    const receipt = { verdict: 'supported', current: true, summary: '<img src=x> Returns to its caller.',
      evidence: ['0x0100 contains RET.'], concerns: [], at: 1, reviewer: 'authored', model: 'test' };
    detail.documentation_reviews = [receipt];
    window.AssemblyWorkUI.renderReview(panel, detail);
    assert(panel.textContent.includes('Explanation supported') && panel.textContent.includes('not human approval'), 'support is not human approval');
    receipt.verdict = 'needs_changes'; receipt.current = false; receipt.concerns = ['The comment claims a memory write that does not occur.'];
    window.AssemblyWorkUI.renderReview(panel, detail);
    assert(panel.textContent.includes('Changes recommended') && panel.textContent.includes('Previous version'), 'obsolete advice cannot look current');
    assert(panel.textContent.includes('What needs attention') && !panel.querySelector('img'), 'specific concerns rendered safely');
    window.AssemblyWorkUI.renderReview(panel, {status: 'open'});
    assert(panel.hidden && !panel.childNodes.length, 'switching away clears the report');
    document.getElementById('report').textContent = 'PASS: independent advice, human flag, historical reports and escaped prose';
  } catch (e) { document.getElementById('report').textContent = 'FAIL: ' + e.stack; }
})();
