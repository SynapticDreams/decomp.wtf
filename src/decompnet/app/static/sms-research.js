"use strict";
/* One operator workflow over existing routes; previews belong to an exact draft, subject and project. */
window.SMSResearchUI = {
  create(root, { api, getSlug, refresh = async () => {} }) {
    const view = window.SMSResearchView;
    root.replaceChildren();
    view.el("h3", "Research and split corrections", root);
    view.el("p", "Inspect evidence before review. Notes and symbols remain research even after review; new structured kinds await qualified discovery consumers. RAM declarations do not capture runtime contents.", root).className = "muted small";
    const bar = view.el("div", undefined, root); bar.className = "row";
    const label = view.el("label", "Research subjects ", bar), scope = view.el("select", undefined, label);
    scope.dataset.research = "scope";
    for (const [value, title] of [["correction", "Split corrections"], ["note", "Notes and archives"], ["symbol", "Symbols"]]) {
      const option = view.el("option", title, scope); option.value = value;
    }
    const buttons = {};
    const button = (key, text, parent, action) => (buttons[key] = view.button(text, parent, key, action));
    button("reload", "Refresh records", bar, () => load());
    button("new", "New proposal", bar, () => { invalidate(); selected = null; details.replaceChildren(); draft.start(subject); sync(); });
    const status = view.el("p", "", root); status.setAttribute("role", "status"); status.dataset.research = "status";
    const list = view.el("div", undefined, root); list.dataset.research = "list";
    button("more", "Next 50 records", root, () => load(cursor));
    const grid = view.el("div", undefined, root); grid.className = "research-grid";
    const inspection = view.el("div", undefined, grid), details = view.el("div", undefined, inspection);
    details.dataset.research = "detail";
    const actions = view.el("div", undefined, inspection); actions.className = "row";
    button("edit", "Edit metadata", actions, () => { invalidate(); draft.start(subject, selected, true); sync(); });
    button("copy", "Copy to new proposal", actions, () => { invalidate(); draft.start(subject, selected); selected = null; sync(); });
    button("accept", "Preview approval", actions, () => decision("review", true));
    button("reject", "Preview rejection", actions, () => decision("review", false));
    button("clear", "Preview metadata detachment", actions, () => decision("clear"));
    button("undo", "Undo correction", actions, () => undo());
    const editor = view.el("div", undefined, grid);
    const draft = window.SMSResearchDraft.create(editor, () => invalidate());
    button("preview", "Preview proposal", editor, () => run(async (current, project) => {
      const body = { slug: project, ...draft.read() };
      selected = null;
      await preview(body, current);
    }));
    button("discard", "Discard draft", root, () => {
      invalidate(); draft.clear();
      if (selected) view.detail(details, selected); else details.replaceChildren();
      status.textContent = "Draft discarded. Stored research is unchanged.";
      sync();
    });
    button("apply", "Apply preview", root, () => apply());
    let slug = null, signature = null, subject = "correction", cursor = null;
    let generation = 0, busy = false, staged = null, selected = null;
    const endpoint = () => ({ correction: "/api/corrections", note: "/api/note", symbol: "/api/symbols/annotation" }[subject]);
    const keyOf = record => subject === "correction" ? record.id : record.key;
    function sync() {
      inspection.hidden = details.childElementCount === 0;
      editor.hidden = draft.box.hidden;
      scope.disabled = busy;
      for (const node of Object.values(buttons)) node.disabled = busy;
      for (const node of list.querySelectorAll("button")) node.disabled = busy;
      buttons.more.hidden = cursor == null;
      buttons.preview.hidden = draft.box.hidden;
      buttons.discard.hidden = draft.box.hidden && !staged;
      buttons.apply.disabled = busy || !staged;
      const available = selected && !staged && draft.box.hidden;
      const editable = available && !selected.archived;
      const supported = available && (selected.annotation?.status === "supported" ||
        selected.annotation?.raw == null && selected.evidence?.status === "supported");
      const reviewable = editable && selected.binding === "current" && selected.evidence?.status === "supported" &&
        (selected.annotation?.status === "supported" || selected.annotation?.raw == null) &&
        (subject === "correction" ? !selected.undone && selected.annotation?.status === "supported" : selected.subject?.status === "supported");
      buttons.accept.hidden = buttons.reject.hidden = !reviewable;
      buttons.accept.disabled = busy || !!selected?.conflict;
      buttons.edit.hidden = !(editable && subject !== "correction" && !["unsupported", "invalid"].includes(selected.application) &&
        (supported || selected.application === "legacy_unknown"));
      buttons.copy.hidden = !supported;
      buttons.clear.hidden = !(editable && subject !== "correction" && ["annotation", "evidence", "subject"].some(field => selected[field]?.raw != null));
      buttons.undo.hidden = !(editable && subject === "correction" && !selected.undone);
    }
    function invalidate() {
      generation++; staged = null; busy = false; draft.box.disabled = false;
      buttons.apply.textContent = "Apply preview";
      status.textContent = "Draft changed. Preview again before applying.";
      sync();
    }
    function clear() {
      invalidate(); selected = null; cursor = null;
      list.replaceChildren(); details.replaceChildren(); draft.clear();
      sync();
    }
    async function run(work, mutation = false) {
      if (!slug || getSlug() !== slug || root.hidden || busy) return;
      const project = slug, token = ++generation;
      const current = () => generation === token && slug === project && getSlug() === project && !root.hidden;
      busy = true; draft.box.disabled = mutation; sync();
      try { await work(current, project); }
      catch (error) {
        if (current()) { staged = null; cursor = null; status.textContent = error.message; }
      } finally { if (current()) { busy = false; draft.box.disabled = false; sync(); } }
    }
    function showList(report) {
      list.replaceChildren();
      const rows = report.corrections || report.records || [];
      for (const record of rows) {
        const key = keyOf(record), name = subject === "correction" ? `${record.where}: ${record.kind}` :
          subject === "note" ? `Note ${key}: ${(record.text || "").slice(0, 160)}` : record.symbol.name;
        const row = view.el("p", undefined, list);
        const node = view.button(`${name} · ${view.summary(record)}`, row, "inspect", () => inspect(key));
        node.dataset.researchKey = String(key);
      }
      if (!rows.length) view.el("p", "No records on this page.", list);
      cursor = subject === "symbol" ? report.next_symbol : report.next_before;
    }
    const query = (project, extra = {}) => `${endpoint()}?${new URLSearchParams({ slug: project, ...extra })}`;
    async function load(next = null) {
      clear();
      return run(async (current, project) => {
        const report = await api(query(project, { limit: 50, ...(next == null ? {} :
          subject === "symbol" ? { after_symbol: next } : { before_id: next }) }));
        if (current()) { showList(report); status.textContent = "Select a record to inspect its evidence, original subject and review authority."; }
      });
    }
    async function inspect(key) {
      invalidate(); selected = null; draft.box.hidden = true; details.replaceChildren();
      return run(async (current, project) => {
        const record = await api(query(project, subject === "symbol" ? { symbol: key } : { id: key }));
        if (current()) { selected = record; view.detail(details, record); status.textContent = "Inspection loaded. Review applies to this stored subject only."; }
      });
    }
    async function preview(body, current) {
      staged = null;
      const result = await api(endpoint(), { method: "POST", body: { ...body, apply: false } });
      if (!current()) return;
      if (typeof result.plan !== "string" || !result.plan) throw new Error("No applicable preview was returned.");
      staged = { path: endpoint(), body, plan: result.plan };
      view.detail(details, result.correction || result.record);
      const effect = result.decision || (body.action === "annotate" ? "replace metadata and reset review" : "store pending research");
      status.textContent = `Preview: ${view.label(effect)}. Inspect the evidence before applying.`;
      buttons.apply.textContent = `Apply: ${view.label(effect)}`;
    }
    async function decision(action, ok) {
      const record = selected;
      if (!record) return;
      invalidate(); selected = null; draft.box.hidden = true;
      return run(async (current, project) => preview({ slug: project, action,
        ...(subject === "symbol" ? { symbol: keyOf(record) } : { id: keyOf(record) }),
        ...(action === "review" ? { ok } : {}) }, current));
    }
    async function updateAfterMutation(current, project, message) {
      status.textContent = message;
      try {
        const report = await api(query(project, { limit: 50 }));
        if (!current()) return;
        showList(report);
        await refresh(project);
      } catch (error) { if (current()) status.textContent = `${message} Refresh failed: ${error.message}`; }
    }
    async function apply() {
      if (!staged) return;
      const request = staged;
      return run(async (current, project) => {
        staged = null;
        const result = await api(request.path, { method: "POST", body: { ...request.body, apply: true, expected_plan: request.plan } });
        if (!current()) return;
        selected = result.correction || result.record;
        draft.box.hidden = true; view.detail(details, selected);
        await updateAfterMutation(current, project, "Applied the preview. Inspection shows the stored research state.");
      }, true);
    }
    async function undo() {
      const record = selected;
      if (!record) return;
      invalidate(); selected = null;
      return run(async (current, project) => {
        await api("/api/corrections/undo", { method: "POST", body: { slug: project, id: record.id } });
        if (!current()) return;
        details.replaceChildren(); draft.box.hidden = true;
        await updateAfterMutation(current, project, "Correction undone; its original evidence remains in history.");
      }, true);
    }
    scope.onchange = () => { subject = scope.value; return load(); };
    draft.box.hidden = true; sync();
    return { render(overview) {
      const enabled = !!overview?.sms_progress && overview.slug === getSlug() && ["sms", "gg"].includes(overview.platform) && overview.kind !== "fork" && overview.room?.role !== "guest";
      const next = JSON.stringify([enabled ? overview.slug : null, overview?.sms_profile, overview?.sms_progress?.input, overview?.room?.role]);
      root.hidden = !enabled;
      if (signature === next) return;
      signature = next; slug = enabled ? overview.slug : null;
      clear();
      status.textContent = enabled ? "Loading research records…" : "";
      if (enabled) return load();
    } };
  }
};
