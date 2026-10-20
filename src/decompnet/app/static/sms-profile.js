"use strict";
/* A small project-settings component. Supplied metadata is rendered as text. */
window.SMSProfileUI = {
  catalogText(catalog) {
    if (!catalog) return "";
    if (!catalog.available) return catalog.message || "";
    const boards = (catalog.matches || []).map(m => `${m.list} list, ${m.board} board (models: ${(m.models || []).join(" or ")})` +
      (m.sms_mode ? ", wired for Master System mode" : "") + (m.battery ? ", battery-backed RAM" : "")).join("; ");
    const source = catalog.source ? ` Source: ${catalog.source.source}, ${catalog.source.license}.` : "";
    return (boards ? `Software-list catalog: ${boards}. ` : "") + catalog.message + source;
  },
  render(panel, view, save, inspect, migration) {
    const token = Symbol();
    panel.profileToken = token;
    panel.replaceChildren();
    if (!view) return;
    const body = document.createElement("div");
    body.className = "pad";
    const heading = document.createElement("h3");
    heading.textContent = "SMS / GG cartridge mapping";
    const status = document.createElement("p");
    status.className = "muted small";
    status.textContent = view.message;
    body.append(heading, status);
    if (inspect) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Inspect mapper evidence";
      const evidence = document.createElement("p");
      evidence.className = "muted small";
      const catalog = document.createElement("p");
      catalog.className = "muted small";
      button.onclick = async () => {
        button.disabled = true;
        catalog.textContent = "";
        try {
          const report = (await inspect()).suggestions;
          const candidates = (report.candidates || []).map(c => c.mapper).join(", ") || "none";
          const offsets = (report.evidence || []).map(e => `${e.mapper} at ROM $${e.offset.toString(16)}`).join("; ");
          evidence.textContent = report.available ? `Low confidence suggestions: ${candidates}. ` +
            `Scanned ${report.scan_bytes} of ${report.total_bytes} bytes; showing ${report.evidence.length} of ` +
            `${report.pattern_count} patterns. ${report.message} ${offsets}` : report.message;
          catalog.textContent = SMSProfileUI.catalogText(report.catalog);
        } catch (error) { evidence.textContent = error.message; }
        finally { button.disabled = false; }
      };
      body.append(button, evidence, catalog);
    }
    const profile = view.profile || {};
    const select = (label, choices, value) => {
      const field = document.createElement("label");
      field.className = "field";
      const title = document.createElement("span");
      title.textContent = label;
      const input = document.createElement("select");
      for (const [key, name] of choices) {
        const option = document.createElement("option");
        option.value = key;
        option.textContent = name;
        input.append(option);
      }
      input.value = value;
      field.append(title, input);
      body.append(field);
      return input;
    };
    const pending = (name) => (view.supported_mappers || []).includes(name) ? "" : " (analysis pending)";
    const mapper = select("Cartridge mapper", [["unknown", "Unresolved"], ["sega", "Sega"],
      ["mapperless", "No mapper" + pending("mapperless")], ["codemasters", "Codemasters" + pending("codemasters")],
      ["korean", "Korean ($A000)" + pending("korean")],
      ["unsupported", "Other unsupported mapper"]], profile.mapper || "unknown");
    const variant = select("Build intent", [["exact-original", "Original reconstruction"],
      ["annotated-original", "Annotated original"], ["experimental", "Experimental / modification research"]],
    profile.variant || "annotated-original");
    const label = document.createElement("label");
    label.className = "field";
    const title = document.createElement("span");
    title.textContent = "Evidence for this choice";
    const reason = document.createElement("textarea");
    reason.value = profile.reason || "";
    reason.minLength = 20;
    reason.maxLength = 1000;
    label.append(title, reason);
    const button = document.createElement("button");
    button.className = "primary small-btn";
    button.type = "button";
    button.textContent = "Save cartridge profile";
    button.onclick = async () => {
      button.disabled = true;
      try { await save({ mapper: mapper.value, variant: variant.value, reason: reason.value }); }
      finally { button.disabled = false; }
    };
    body.append(label, button);
    panel.append(body);
    if (migration) window.SMSProfileMigrationUI.render(body,
      () => ({ mapper: mapper.value, variant: variant.value, reason: reason.value }), migration.run,
      () => panel.profileToken === token && panel.isConnected && !panel.hidden && migration.current(),
      migration.applied, (busy, commit) => {
        button.disabled = busy;
        if (commit) mapper.disabled = variant.disabled = reason.disabled = busy;
      });
  }
};
