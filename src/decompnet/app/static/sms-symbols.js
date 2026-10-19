"use strict";
/* Source identity and declared coordinates are reviewable; candidate labels do not establish semantic meaning. */
window.SMSSymbolUI = {
  create(root, { api, getSlug, refresh, notify = () => {} }) {
    const node = key => root.querySelector(`[data-symbol="${key}"]`);
    const buttons = ["preview", "apply", "inspect", "more", "remove"];
    node("status").style.overflowWrap = node("records").style.overflowWrap = "anywhere";
    let slug = null, generation = 0, preview = null, view = null, metadata, busy = false;
    const label = value => String(value || "unknown").replaceAll("_", " ");
    const hex = (value, width = 4) => typeof value === "number" ? value.toString(16).padStart(width, "0") : "?";
    const text = value => { node("status").textContent = value; };
    function sync() {
      for (const key of buttons) node(key).disabled = busy;
      node("apply").disabled = busy || !preview;
      node("inspect").disabled = node("remove").disabled = busy || !metadata;
      node("more").hidden = view?.next == null;
      node("more").disabled = busy || view?.next == null;
    }
    function clear() {
      generation++;
      preview = view = null;
      busy = false;
      node("records").replaceChildren();
      sync();
    }
    function show(report, mode) {
      const counts = Object.entries(report.counts || {}).map(([key, count]) => `${label(key)}: ${count}`).join(", ");
      text(`${label(report.state)} · ${report.record_count} records · ${report.names} candidate names for code · ` +
        `${report.seeds} seed suggestions for code · ${report.alias_count} code aliases. Semantic meanings remain unreviewed. ` +
        `${counts}. Source SHA256: ${report.source?.sha256 || "unavailable"}. ` +
        `Normalized input SHA256: ${report.input?.sha256 || "unavailable"}.` +
        (report.notice ? " An adjacent source or layout was rejected; inspect the records and supply a valid declaration." : ""));
      node("records").replaceChildren();
      const range = document.createElement("p");
      range.textContent = report.records.length
        ? `Records ${report.offset + 1}–${report.offset + report.records.length} of ${report.record_count}.`
        : `No records on this page (${report.record_count} total).`;
      node("records").append(range);
      const list = document.createElement("ul");
      for (const record of report.records) {
        const item = document.createElement("li");
        const coordinates = (record.coordinates || []).map(c => `slot ${c.slot}, ${c.space}` +
          (c.rom_offset == null ? "" : `, ROM $${hex(c.rom_offset, 6)} (physical bank ${c.physical_bank})`) +
          (c.reason ? `: ${c.reason}` : "")).join("; ");
        item.textContent = `Line ${record.line}: ${record.name} · source ${hex(record.bank)}:${hex(record.cpu)} · ` +
          `${label(record.status)}${coordinates ? " · " + coordinates : ""}` +
          (record.coordinates_truncated ? ` · showing 32 of ${record.coordinate_count} candidate coordinates` : "");
        list.append(item);
      }
      node("records").append(list);
      view = { mode, next: report.next_offset, source: report.source_id, context: report.inspection_context };
      node("apply").textContent = report.state === "declared" ? "Apply declared source" : "Store pending source";
      sync();
    }
    async function run(work) {
      const token = ++generation, project = slug;
      const current = () => generation === token && slug === project && getSlug() === project;
      busy = true;
      sync();
      try { await work(current, project); }
      catch (error) {
        if (current()) { preview = view = null; node("records").replaceChildren(); text(error.message); }
      } finally { if (current()) { busy = false; sync(); } }
    }
    async function body(project) {
      const source = node("source").files[0], layout = node("layout").files[0];
      if (!source) throw new Error("Choose the original symbol source to preview it.");
      if (source.size > 8 * 1024 * 1024 || (layout && layout.size > 2 * 1024 * 1024))
        throw new Error("Symbol sources are limited to 8 MiB and declarations to 2 MiB.");
      const bytes = new Uint8Array(await source.arrayBuffer());
      let binary = "";
      for (let at = 0; at < bytes.length; at += 32768) binary += String.fromCharCode(...bytes.subarray(at, at + 32768));
      const declaration = layout ? JSON.parse(await layout.text()) : null;
      if (layout && (!declaration || typeof declaration !== "object" || Array.isArray(declaration)))
        throw new Error("The layout JSON must contain a declaration object.");
      return { slug: project, name: source.name, source_base64: btoa(binary), layout: declaration };
    }
    node("preview").onclick = () => run(async (current, project) => {
      const source = await body(project);
      if (!current()) return;
      const result = await api("/api/symbols/import", { method: "POST", body: { ...source, apply: false } });
      if (!current()) return;
      preview = { body: source, plan: result.plan };
      show(result.symbol_file, "preview");
    });
    node("inspect").onclick = () => run(async (current, project) => {
      const result = await api("/api/symbols/inspect", { method: "POST", body: { slug: project } });
      if (!current()) return;
      preview = null;
      show(result, "stored");
    });
    node("more").onclick = () => run(async (current, project) => {
      const requested = view, staged = preview;
      if (requested?.next == null) return;
      let report;
      if (requested.mode === "preview") {
        const result = await api("/api/symbols/import", { method: "POST", body: { ...staged.body, apply: false,
          expected_plan: staged.plan, offset: requested.next } });
        report = result.symbol_file;
      } else report = await api("/api/symbols/inspect", { method: "POST", body: {
        slug: project, expected_source: requested.source, expected_context: requested.context, offset: requested.next } });
      if (current()) show(report, requested.mode);
    });
    node("apply").onclick = () => run(async (current) => {
      if (!preview) return;
      await api("/api/symbols/import", { method: "POST", body: { ...preview.body, apply: true, expected_plan: preview.plan } });
      if (!current()) return;
      preview = view = null;
      node("records").replaceChildren();
      notify("Symbol source stored. Preview resplitting to inspect its effect on newly discovered routines.");
      await refresh();
    });
    node("remove").onclick = () => run(async (current, project) => {
      await api("/api/symbols/remove", { method: "POST", body: { slug: project } });
      if (!current()) return;
      preview = view = null;
      node("records").replaceChildren();
      notify("Symbol source disabled; its private provenance is retained.");
      await refresh();
    });
    for (const key of ["source", "layout"]) node(key).onchange = () => {
      clear();
      text(`Selected source: ${node("source").files[0]?.name || "none"}; layout: ${node("layout").files[0]?.name || "none"}. Preview before applying.`);
    };
    return { render(overview, source) {
      const enabled = !!overview?.sms_progress;
      root.hidden = !enabled;
      if (!enabled || slug !== overview.slug) {
        slug = enabled ? overview.slug : null;
        metadata = undefined;
        clear();
        node("source").value = node("layout").value = "";
        text("Choose the original symbol source and optional layout JSON, then preview it. Without a declaration, labels remain pending.");
      }
      if (enabled && source !== undefined) {
        const old = [metadata?.source_id, metadata?.state, metadata?.inspection_context].join(":");
        const next = [source?.source_id, source?.state, source?.inspection_context].join(":");
        if (metadata !== undefined && old !== next) clear();
        metadata = source;
        if (!preview && !view) text(source ? `${label(source.state)} · ${source.names} candidate names for code. Inspect the stored source or preview a replacement.` : "No active symbol source.");
        sync();
      }
    } };
  }
};
