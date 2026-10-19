"use strict";
/* Inspect one page at a time. Every response must belong to the original preview. */
window.ResplitInspectionUI = {
  render(panel, report, load, current, invalidate) {
    const root = document.createElement("div");
    panel.append(root);
    const live = () => root.isConnected && current();
    const fail = error => {
      if (!live()) return;
      root.textContent = `${error.message} Preview again before applying.`;
      invalidate();
    };
    const heading = document.createElement("p");
    heading.className = "muted small";
    const limits = report.source_revalidation_limits;
    heading.textContent = `${report.source_revalidation_pending || 0} accepted sources need checks on apply. ` +
      (limits ? `Automatic checks have a ${limits.functions}-function / ${limits.seconds}-second budget. ` : "") +
      "Failed, unresolved or budget-limited source stays unaccepted. Names and purposes need review.";
    root.append(heading);
    const overlaps = document.createElement("div");
    const address = value => Number.isInteger(value) ? `$${value.toString(16)}` : "unknown";
    const position = row => `ROM ${address(row.rom_offset)}, CPU ${address(row.cpu)}, ${row.size} bytes`;
    const section = (kind, title, initial, functionId = null, target = root) => {
      const box = document.createElement("div"), status = document.createElement("p"), list = document.createElement("ul");
      const previous = document.createElement("button"), next = document.createElement("button");
      previous.type = next.type = "button";
      previous.textContent = `Previous ${title}`;
      next.textContent = `Next ${title}`;
      box.append(status, list, previous, next);
      target.append(box);
      let page = initial, generation = 0;
      const visible = () => live() && box.isConnected;
      const show = value => {
        page = value;
        list.replaceChildren();
        status.textContent = `${title}: ${value.total ? value.offset + 1 : 0}–` +
          `${value.offset + value.rows.length} of ${value.total}.`;
        for (const row of value.rows) {
          const item = document.createElement("li");
          item.textContent = kind === "overlaps" ? position(row) :
            `${row.name}${row.name_truncated ? "…" : ""}: ${position(row)}; ${row.status}. ` +
            (kind === "checks" ? (row.proposed ? `Proposed ${position(row.proposed)}.` : "No proposed entry at this offset.") :
              `${row.overlap_count} overlapping candidates; saved work will be archived on apply.`);
          if (kind === "changed" && row.overlap_count) {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = `Inspect overlaps for ${row.id}`;
            button.onclick = () => {
              overlaps.replaceChildren();
              section("overlaps", `overlaps for ${row.id}`, null, row.id, overlaps);
            };
            item.append(button);
          }
          list.append(item);
        }
        previous.disabled = value.offset === 0;
        next.disabled = value.next_offset === null;
      };
      const request = async offset => {
        const started = ++generation;
        previous.disabled = next.disabled = true;
        try {
          const response = await load({ kind, offset, ...(functionId === null ? {} : { function: functionId }) });
          if (!visible() || generation !== started) return;
          const value = response.inspection;
          if (response.plan !== report.plan || !value || value.kind !== kind || value.offset !== offset ||
              !Array.isArray(value.rows) || value.rows.length > 100 ||
              value.limit !== 100 || !Number.isInteger(value.total) || value.total < offset ||
              value.rows.length !== Math.min(100, value.total - offset) ||
              value.next_offset !== (offset + value.rows.length < value.total ? offset + value.rows.length : null) ||
              (functionId !== null && value.function?.id !== functionId)) throw new Error("Preview inspection changed.");
          show(value);
        } catch (error) { if (visible() && generation === started) fail(error); }
      };
      previous.onclick = () => request(Math.max(0, page.offset - page.limit));
      next.onclick = () => request(page.next_offset);
      if (initial) show(initial);
      else request(0);
    };
    section("changed", "changed routines", { offset: 0, total: report.changed_work_count,
      rows: report.changed_work, limit: 100, next_offset: report.changed_work_truncated ? 100 : null });
    if (report.source_revalidation_pending) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Inspect accepted source checks";
      button.onclick = () => { button.remove(); section("checks", "accepted source checks", null); };
      root.append(button);
    }
    root.append(overlaps);
  }
};
