/* Actual assembly drawer -> real guarded queue and launcher APIs, using an authored project only. */
(async () => {
  const assert = (x, why) => { if (!x) throw new Error(why); };
  try {
    poll = () => {};
    S.slug = 'authored'; S.tab = 'functions'; S.claims = [];
    S.ov = { platform: 'gbc', priority: [] };
    S.st = { settings: {}, agents: [{ id: 'claude', name: 'Authored helper', installed: true, models: [], efforts: [] }] };
    const map = await api('/api/map?slug=authored');
    S.map = map.rows.map((row, i) => ({ ...Object.fromEntries(map.keys.map((key, j) => [key, row[j]])), i }));
    S.fn = 'First'; S.editDirty = false;
    document.getElementById('drawer').hidden = false;
    await refreshFn(true);
    assert(document.getElementById('fnWork').textContent === 'Document this function', 'assembly has a pinned action');
    assert(!document.getElementById('fnWork').hidden && document.getElementById('fnWork').disabled, 'deferred work cannot launch');
    assert(document.getElementById('fnAssemblyWork').textContent.includes('Bytes identical: 1 / 1'), 'receipt visible in the real drawer');
    assert(!document.getElementById('fnResume').hidden, 'resume is an explicit action');
    await document.getElementById('fnResume').onclick();
    assert(!document.getElementById('fnWork').disabled, 'resume restores assembly eligibility');
    document.getElementById('fnWork').onclick();
    assert(document.getElementById('dialog').textContent.includes('Document First'), 'assembly dialog does not ask for C matching');
    assert(document.getElementById('phLean').hidden && document.getElementById('phPolish').closest('label').hidden, 'C-only methods are hidden');
    await document.getElementById('phGo').onclick();
    assert(document.getElementById('dialog').hidden, 'pinned launch completed through the API');
    await refreshFn(false);
    document.getElementById('fnDefer').onclick();
    document.getElementById('asmDeferReason').value = '<img src=x> authored mapping evidence needs review';
    await document.getElementById('asmDeferGo').onclick({ target: document.getElementById('asmDeferGo') });
    assert(document.getElementById('fnWork').disabled && !document.getElementById('fnResume').hidden, 'defer keeps this routine off helpers');
    assert(!document.getElementById('fnAssemblyWork').querySelector('img'), 'stored reasons are escaped');
    const refreshed = await api('/api/map?slug=authored');
    S.map = refreshed.rows.map((row, i) => ({ ...Object.fromEntries(refreshed.keys.map((key, j) => [key, row[j]])), i }));
    L.filter = 'deferred'; renderList();
    assert(document.getElementById('fnRows').textContent.includes('Bytes exact') &&
      !document.getElementById('fnRows').textContent.includes('99.'), 'assembly queue separates byte equality from checks');
    document.getElementById('report').textContent = 'PASS: production assembly drawer, queue actions, guarded launcher and byte/check separation';
  } catch (e) { document.getElementById('report').textContent = 'FAIL: ' + e.stack; }
})();
