"use strict";
/* The editor emits fresh pending evidence. Stored bindings and review receipts are never copied into writes. */
window.SMSResearchDraft = {
  create(parent, changed) {
    const view = window.SMSResearchView, templates = window.SMSResearchTemplates;
    const box = view.el("fieldset", undefined, parent), fields = {}, wrappers = {};
    view.el("legend", "Research proposal", box);
    const field = (key, title, type = "input", options = null) => {
      const wrap = view.el("label", title, box), input = view.el(type, undefined, wrap);
      wrap.className = "research-field"; wrappers[key] = wrap;
      input.dataset.researchInput = key;
      if (type === "textarea") input.rows = key === "spec" ? 8 : 3;
      if (type === "input") input.type = "text";
      if (options) for (const [value, label] of options) {
        const option = view.el("option", label, input); option.value = value;
      }
      input.oninput = changed;
      fields[key] = input;
      return input;
    };
    const heading = view.el("p", "", box);
    field("symbol", "Existing symbol name").maxLength = 256;
    field("text", "Note text (1–4,000 characters)", "textarea").maxLength = 8000;
    field("function", "Attach new note to function (optional)").maxLength = 256;
    field("reason", "How you know (20–1,000 characters)", "textarea").maxLength = 2000;
    field("at", "CPU placement for legacy hints (bank:address, for example 00:0100)").maxLength = 64;
    field("kind", "Declaration kind", "select");
    field("space", "Target address space", "select", [["rom", "Physical ROM"], ["wram", "WRAM (contents unobserved)"], ["cart_ram", "Cartridge RAM (contents unobserved)"]]);
    field("offset", "Byte offset in that space (decimal or 0x hex)").inputMode = "numeric";
    field("size", "Byte extent (decimal or 0x hex)").inputMode = "numeric";
    field("spec", "Layout specification (JSON; edit the example for your evidence)", "textarea").maxLength = 65536;
    field("state", "Evidence state", "select", ["unknown", "observation", "static_derivation", "interpretation", "hypothesis"].map(x => [x, view.label(x)]));
    field("confidence", "Confidence", "select", ["unknown", "low", "medium", "high"].map(x => [x, x]));
    field("alternatives", "Alternative interpretations (one per line, at most eight)", "textarea").maxLength = 8199;
    field("links", 'Evidence links (JSON array of {"kind":"analysis","ref":"reference","sha256":null})', "textarea").maxLength = 65536;
    view.el("p", "Examples are geometry templates, not observations. Observation, static derivation and interpretation need an evidence reference. New proposals receive fresh project bindings and pending review.", box).className = "muted small";
    let subject = "correction", key = null;
    const geometry = () => {
      for (const name of ["space", "offset", "size", "spec"]) wrappers[name].hidden = fields.kind.value === "none";
    };
    fields.kind.onchange = () => {
      if (fields.kind.value !== "none") {
        const example = templates.example(fields.kind.value);
        fields.size.value = example.size;
        fields.spec.value = JSON.stringify(example.spec, null, 2);
      }
      geometry(); changed();
    };
    fields.state.onchange = () => {
      if (fields.state.value === "unknown") fields.confidence.value = "unknown";
      changed();
    };
    const number = name => {
      const raw = fields[name].value.trim();
      if (!/^(?:0x[0-9a-f]+|[0-9]+)$/i.test(raw) || !Number.isSafeInteger(Number(raw)))
        throw new Error(`${name} must be an exact nonnegative integer.`);
      return Number(raw);
    };
    const json = name => {
      try { return window.ResearchJSON.parse(fields[name].value); }
      catch (error) { throw new Error(`${name}: ${error.message}`); }
    };
    const start = (kind, record = null, editing = false) => {
      subject = kind; key = editing ? record.key : null;
      box.hidden = false; box.disabled = false;
      for (const name of ["symbol", "text", "function", "reason", "at"]) fields[name].value = "";
      for (const name of ["symbol", "text", "function", "reason", "at"]) wrappers[name].hidden =
        name === "symbol" ? kind !== "symbol" : ["text", "function"].includes(name) ? kind !== "note" : kind !== "correction";
      fields.text.readOnly = editing; fields.function.disabled = editing;
      fields.symbol.readOnly = editing;
      fields.space.disabled = kind === "correction";
      fields.kind.replaceChildren();
      for (const name of [...(kind === "correction" ? [] : ["none"]), ...templates.kinds]) {
        const option = view.el("option", name === "none" ? "Evidence only (no typed range)" : view.label(name), fields.kind);
        option.value = name;
      }
      fields.kind.value = kind === "correction" ? "data" : "none";
      fields.space.value = "rom"; fields.offset.value = "0";
      fields.kind.onchange();
      fields.state.value = "hypothesis"; fields.confidence.value = "low";
      fields.alternatives.value = ""; fields.links.value = "[]";
      heading.textContent = editing ? "Replace metadata on this exact subject; original research is archived and review returns to pending. Note prose and attachment stay unchanged." :
        "Create a new pending proposal. Existing corrections and archived evidence remain stored.";
      if (record) {
        const value = record.annotation?.value, evidence = record.evidence?.value;
        if (value) {
          fields.kind.value = value.kind; fields.space.value = value.target.space;
          fields.offset.value = value.target.offset; fields.size.value = value.target.size;
          fields.spec.value = JSON.stringify(value.spec, null, 2);
        }
        if (evidence) {
          fields.state.value = evidence.state; fields.confidence.value = evidence.confidence;
          fields.alternatives.value = evidence.alternatives.join("\n");
          fields.links.value = JSON.stringify(evidence.links, null, 2);
        }
        fields.symbol.value = kind === "symbol" ? record.key : "";
        fields.text.value = record.archived ? (record.subject?.value?.entity?.text || "") : (record.text || "");
        fields.reason.value = record.reason || "";
        fields.at.value = record.where?.includes(":") ? record.where : "";
      }
      geometry();
    };
    return {
      box, start,
      clear() {
        key = null;
        for (const field of Object.values(fields)) field.value = "";
        box.hidden = true; box.disabled = false;
      },
      read() {
        let annotation = null;
        if (fields.kind.value !== "none") {
          const spec = json("spec");
          if (!spec || typeof spec !== "object" || Array.isArray(spec)) throw new Error("The layout specification must be a JSON object.");
          annotation = { version: 1, kind: fields.kind.value, target: {
            space: fields.space.value, offset: number("offset"), size: number("size") }, spec };
        }
        const links = json("links"), alternatives = fields.alternatives.value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
        if (!Array.isArray(links) || links.length > 16) throw new Error("Use an array of at most 16 evidence links.");
        if (alternatives.length > 8 || alternatives.some(x => [...x].length > 512)) throw new Error("Use at most eight alternatives of 512 characters each.");
        if (fields.state.value === "unknown" && fields.confidence.value !== "unknown") throw new Error("Unknown evidence requires unknown confidence.");
        if (["observation", "static_derivation", "interpretation"].includes(fields.state.value) && !links.length)
          throw new Error("This evidence state needs an evidence reference.");
        const evidence = { version: 1, revision: null, context: null, subject_sha256: null, origin: null,
          state: fields.state.value, confidence: fields.confidence.value, alternatives, links,
          review: { state: "pending", actor: null, at: null, binding_sha256: null } };
        if (subject === "correction") return { action: "create", kind: annotation.kind, annotation, evidence,
          at: fields.at.value.trim(), reason: fields.reason.value, count: 0 };
        if (subject === "symbol") return { action: "annotate", symbol: key ?? fields.symbol.value, annotation, evidence };
        if (key !== null) return { action: "annotate", id: key, text: "", annotation, evidence };
        if (!fields.text.value.trim() || [...fields.text.value].length > 4000) throw new Error("A new note needs 1–4,000 characters.");
        return { action: "create", text: fields.text.value, function: fields.function.value || null, annotation, evidence };
      }
    };
  }
};
