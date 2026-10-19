/* The last submitted assembly's mechanical checks, distinct from semantic approval. */
"use strict";
window.AssemblyWorkUI = {
  render(panel, detail) {
    panel.replaceChildren();
    const work = detail?.assembly_work;
    panel.hidden = !work;
    if (!work) return;
    const line = (text, cls = "small") => {
      const p = document.createElement("p");
      p.className = cls;
      p.textContent = text;
      panel.append(p);
    };
    if (work.deferred) {
      line("Documentation deferred", "col-title");
      line(work.reason);
      line("Helpers skip this routine until its evidence changes or you resume documentation.");
    } else if (work.evidence_changed) line("Evidence changed: this routine is eligible for another check.");
    const v = work.validation;
    if (!v) { line("No saved assembly validation yet. Submit a draft to see its checks."); return; }
    line("Latest submitted assembly", "col-title");
    if (!v.current) line("Previous context: layout, names, mapping or validator changed. Check the current draft again.");
    line(v.byte_identical ? `Bytes identical: ${v.target} / ${v.target}.` :
      `Matching byte prefix: ${v.same} / ${v.target}; assembled ${v.assembled} bytes.`);
    const states = { passed: "Passed", failed: "Needs work", pending: "Pending evidence", not_checked: "Not checked" };
    const list = document.createElement("ul");
    for (const check of v.checks || []) {
      const item = document.createElement("li");
      item.textContent = `${check.label}: ${states[check.state] || "Not checked"}`;
      for (const problem of check.problems || []) {
        const p = document.createElement("p"); p.className = "small"; p.textContent = problem; item.append(p);
      }
      if (check.truncated) { const p = document.createElement("p"); p.textContent = "Additional problems omitted."; item.append(p); }
      list.append(item);
    }
    panel.append(list);
    line("These checks cover assembly and placement. Names and behavior still need review.");
  },
};
