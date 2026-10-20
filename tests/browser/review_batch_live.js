/* Production controls -> guarded batch API -> pause/resume -> comment correction and evidence follow-up. */
(async () => {
  const assert = (x, why) => { if (!x) throw new Error(why); };
  const wait = async (state) => {
    for (let i=0;i<200;i++) {
      const batch = await api('/api/documented/batch?slug=authored');
      if (batch.state === state) return batch;
      await new Promise((resolve)=>setTimeout(resolve,20));
    }
    throw new Error(`batch never reached ${state}`);
  };
  try {
    poll = () => {};
    S.slug='authored'; S.tab='functions'; S.claims=[]; S.sessions=[]; S.reviewBatch=null;
    S.ov={platform:'gbc',priority:[]};
    S.st={settings:{},agents:[{id:'claude',name:'Authored reviewer',installed:true,models:[],efforts:[]},
      {id:'codex',name:'Authored writer',installed:true,models:[],efforts:[]}]};
    const map=await api('/api/map?slug=authored');
    S.map=map.rows.map((row,i)=>({...Object.fromEntries(map.keys.map((key,j)=>[key,row[j]])),i}));
    renderList();
    assert(!document.getElementById('fnReviewBatch').hidden,'assembly projects offer Review remaining');
    document.getElementById('fnReviewBatch').onclick();
    assert(document.getElementById('dialogTitle').textContent === 'Review remaining','dedicated batch dialog');
    assert(document.getElementById('dialog').textContent.includes('independently reviewed'),'correction safeguards explained');
    const writer=document.getElementById('batchWriterWho'); writer.value='k:codex'; writer.onchange();
    document.getElementById('batchSessions').value='1';
    await document.getElementById('batchStart').onclick();
    S.reviewBatch=await wait('paused'); renderReviewBatch();
    assert(document.getElementById('reviewBatchPanel').textContent.includes('session limit'),'usage limit pauses clearly');
    const resume=[...document.querySelectorAll('#reviewBatchPanel button')].find((b)=>b.textContent.includes('Resume review batch'));
    resume.onclick();
    assert(document.getElementById('dialogTitle').textContent === 'Resume review batch','resume preserves scope');
    document.getElementById('batchSessions').value='2';
    await document.getElementById('batchStart').onclick();
    S.reviewBatch=await wait('complete'); renderReviewBatch();
    const panel=document.getElementById('reviewBatchPanel');
    assert(panel.textContent.includes('1 corrected') && panel.textContent.includes('1 need evidence'),'batch outcomes shown');
    assert(!panel.querySelector('img'),'follow-up prose is escaped');
    const first=await api('/api/function?slug=authored&name=First');
    const second=await api('/api/function?slug=authored&name=Second');
    assert(first.source.includes('Returns immediately') && first.sample,'corrected source keeps human flag');
    assert(second.documentation_followup?.text.includes('<img src=x>') && second.sample,'existing uncertainty becomes saved follow-up');
    S.fn='Second'; S.editDirty=false; document.getElementById('drawer').hidden=false; await refreshFn(true);
    assert(document.getElementById('fnDocumentationReview').textContent.includes('Saved follow-up'),'follow-up visible on routine');
    document.getElementById('report').textContent='PASS: batch controls, limits, resume, independent correction and saved existing findings';
  } catch(e) { document.getElementById('report').textContent='FAIL: '+e.stack; }
})();
