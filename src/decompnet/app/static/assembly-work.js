/* The last submitted assembly's mechanical checks, distinct from semantic approval. */
"use strict";
window.AssemblyWorkUI = {
  renderReview(panel, detail, running = false) {
    panel.replaceChildren();
    const reports = detail.documentation_reviews || [];
    panel.hidden = detail.status !== "documented" && !reports.length;
    if (panel.hidden) return;
    const line = (parent, text, cls = "small") => {
      const p = document.createElement("p"); p.className = cls; p.textContent = text; parent.append(p);
    };
    line(panel, "Independent AI review", "col-title");
    line(panel, detail.sample ? "Human review pending. You can leave this flag in place if you cannot assess the assembly." :
      "AI assessments are separate from human review and byte-matching checks.");
    if (running) line(panel, "Review in progress. The report will appear here when the helper saves it.");
    if (!reports.length) {
      if (!running) line(panel, "Ask AI to review for a plain-English explanation, supporting evidence and anything uncertain.");
      return;
    }
    const outcomes = { supported: "Explanation supported", needs_changes: "Changes recommended", uncertain: "Uncertain" };
    reports.forEach((report, i) => {
      let box = panel;
      if (i) {
        box = document.createElement("details");
        const title = document.createElement("summary"); title.textContent = "Earlier AI review"; box.append(title); panel.append(box);
      }
      line(box, `AI assessment: ${outcomes[report.verdict] || "Uncertain"}.`);
      if (report.candidate && !report.applied) line(box, "Review of proposed comments. Accepted source is unchanged.");
      if (report.applied) line(box, "Comment correction applied after assembly validation and independent review.");
      if (!report.current) line(box, "Previous version: source or supporting context changed. Ask for a fresh review before using this assessment.");
      line(box, report.summary);
      for (const [key, title] of [["evidence", "Supporting evidence"], ["concerns", "What needs attention"]]) {
        if (!(report[key] || []).length) continue;
        line(box, title, "col-title");
        const list = document.createElement("ul");
        for (const text of report[key]) { const li = document.createElement("li"); li.textContent = text; list.append(li); }
        box.append(list);
      }
      line(box, `${report.reviewer || "AI helper"} · ${report.model || "default model"} · ${new Date(report.at * 1000).toLocaleString()}`, "muted small");
    });
    line(panel, "An AI assessment is advice, not human approval. Human-review flags are never cleared by a report.");
    if (detail.documentation_followup) {
      const followup = detail.documentation_followup;
      line(panel, `Saved follow-up: ${followup.kind === "layout" ? "layout investigation" : "evidence needed"}`, "col-title");
      if (!followup.current) line(panel,"Previous context: check this follow-up against the current source.");
      line(panel,followup.text);
    }
  },
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
