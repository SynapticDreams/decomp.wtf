/* Authored production drawer -> real guarded launcher -> scripted read-only reviewer -> saved report. */
(async () => {
  const assert = (x, why) => { if (!x) throw new Error(why); };
  try {
    poll = () => {};
    S.slug = 'authored'; S.tab = 'functions'; S.claims = []; S.sessions = [];
    S.ov = { platform: 'gbc', priority: [] };
    S.st = { settings: {}, agents: [{ id: 'claude', name: 'Authored helper', installed: true, models: [], efforts: [] }] };
    const map = await api('/api/map?slug=authored');
    S.map = map.rows.map((row, i) => ({ ...Object.fromEntries(map.keys.map((key, j) => [key, row[j]])), i }));
    S.fn = 'First'; S.editDirty = false;
    document.getElementById('drawer').hidden = false;
    await refreshFn(true);
    assert(!document.getElementById('fnAIReview').hidden, 'documented routines offer AI review');
    const header = document.querySelector('#drawer .drawer-head');
    assert(header.scrollWidth <= header.clientWidth, 'review controls fit the function drawer');
    assert(document.getElementById('fnDocumentationReview').textContent.includes('Human review pending'), 'non-assembly users can leave flags pending');
    document.getElementById('fnAIReview').onclick();
    assert(document.getElementById('dialogTitle').textContent === 'Review First', 'review has its own dialog');
    assert(document.getElementById('dialog').textContent.includes('plain-English'), 'review purpose is explained');
    assert(document.getElementById('phLean').hidden && document.getElementById('phStall').closest('label').hidden &&
      document.getElementById('phPolish').closest('label').hidden, 'review excludes documentation/C retry options');
    await document.getElementById('phGo').onclick();
    for (let i = 0; i < 100; i++) {
      const detail = await api('/api/function?slug=authored&name=First');
      if (detail.documentation_reviews.length) break;
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    await refreshFn(false);
    const panel = document.getElementById('fnDocumentationReview');
    assert(panel.textContent.includes('AI assessment: Uncertain') && panel.textContent.includes('What needs attention'), 'structured review saved and shown');
    assert(panel.textContent.includes('0x0100') && panel.textContent.includes('returns to its caller'), 'plain-English summary and concrete evidence visible');
    assert(panel.textContent.includes('<img src=x>') && !panel.querySelector('img'), 'reviewer text cannot inject markup');
    assert(document.getElementById('fnStatus').textContent.includes('look it over') && !document.getElementById('fnLooksRight').hidden,
      'AI report never clears human-review flag');
    assert(S.st.settings.review_helper && !S.st.settings.pin_helper, 'review helper preferences are separate');
    document.getElementById('report').textContent = 'PASS: production review launch, helper report, evidence, escaped text and human flag retained';
  } catch (e) { document.getElementById('report').textContent = 'FAIL: ' + e.stack; }
})();
