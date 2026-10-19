"use strict";
/* Separate evidence dimensions. Values from projects and receipts are rendered only as text. */
window.SMSProgressUI = {
  timeline(svg, timeline, now = Date.now() / 1000) {
    svg.replaceChildren();
    const points = timeline?.points || [];
    if (points.length < 2 || !timeline.bytes) return;
    const start = points[0][0], end = Math.max(now, points[points.length - 1][0] + 1);
    const y = value => (42 - 40 * value / Math.max(timeline.bytes, 1)).toFixed(1);
    let path = `M0,${y(timeline.baseline_bytes)}`;
    for (const [time, bytes] of points) path += `H${(200 * (time - start) / (end - start)).toFixed(1)}V${y(bytes)}`;
    path += "H200";
    for (const [cls, data] of [["area", `${path}V44H0Z`], ["line", path]]) {
      const node = document.createElementNS("http://www.w3.org/2000/svg", "path");
      node.setAttribute("class", cls); node.setAttribute("d", data); svg.append(node);
    }
  },
  render(panel, overview) {
    panel.replaceChildren();
    if (!overview.sms_progress) return;
    const metrics = overview.sms_progress;
    const line = text => {
      const node = document.createElement("p");
      node.className = "small";
      node.textContent = text;
      panel.append(node);
    };
    const amount = bytes => `${Number(bytes || 0).toLocaleString()} bytes`;
    line(`Current original input: ${metrics.input?.status || "unknown"}.`);
    line(`Discovered code: ${amount(metrics.discovered_code_bytes)}; stored assembly acceptance: ` +
      `${amount(metrics.documented_assembly.bytes)}; stored C byte references: ${amount(metrics.c_reference.bytes)}.`);
    line(`Classified data: ${amount(metrics.classified_data.bytes)}; overlaps with code: ` +
      `${amount(metrics.classified_data.code_overlap_bytes)}. Typed data remains unqualified.`);
    line(`Semantic review: ${metrics.semantic_review.pending} pending, ${metrics.semantic_review.unknown} unknown; ` +
      "legacy sampling does not establish approval. C references are not linked replacements. Runtime parity is not tested.");
    const last = overview.export;
    if (!last) { line("No export verification recorded."); return; }
    if (!last.verification) { line("The older export record is unqualified. Export again for a structured result."); return; }
    const report = last.verification;
    line(`Last export: ${last.current ? "project metadata, input and exported tree still match" : "historical / current context differs or evidence is unavailable"}. ` +
      `Overall verification ${report.passed ? "passed" : "failed"}; ` +
      `whole-image equality ${report.image?.checked && report.image.equal === true ? "passed at that build" : report.image?.checked ? "different at that build" : "not verified"}.`);
    if (report.receipt_valid) {
      line(`Assembly actually inserted: ${report.documented.inserted} of ${report.documented.expected} routines, ` +
        `${amount(report.documented.inserted_bytes)}; ${report.documented.omitted} omitted. ` +
        `Strict insertion ${report.documented.required ? "required" : "optional"}.`);
      for (const item of report.documented.omissions || []) line(`${item.name}: ${item.reason}`);
      if (report.documented.omissions_truncated) line("Additional omission details are in build/verification.json.");
    } else line("Source insertion was not verified for that attempt.");
    if (report.errors?.length) line(`Check results: ${report.errors.join(", ")}`);
  },
  result(panel, result) {
    panel.replaceChildren();
    const report = result.verification;
    const node = document.createElement("p");
    node.textContent = `Export verification ${report?.passed ? "passed" : "failed"}. ` +
      `Whole-image equality: ${report?.image?.checked && report.image.equal === true ? "equal" : report?.image?.checked ? "different" : "not verified"}; ` +
      `${result.documented || 0} assembly routines inserted; ${(result.left_out || []).length} omitted. ` +
      "C remains reference material; runtime parity is not tested.";
    panel.append(node);
    for (const [name, reason] of (result.left_out || []).slice(0, 100)) {
      const detail = document.createElement("p");
      detail.textContent = `${name}: ${reason}`;
      panel.append(detail);
    }
    if ((result.left_out || []).length > 100) {
      const more = document.createElement("p");
      more.textContent = "Showing 100 omissions; full details are in the exported verification report.";
      panel.append(more);
    }
  }
};
