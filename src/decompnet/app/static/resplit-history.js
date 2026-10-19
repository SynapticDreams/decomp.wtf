"use strict";
/* Local recovery history. All project values are rendered as text. */
window.ResplitHistoryUI = {
  async render(panel, load, undo, archive) {
    const token = Symbol();
    panel.historyToken = token;
    panel.replaceChildren();
    const heading = document.createElement("h3");
    heading.textContent = "Resplit history";
    const status = document.createElement("p");
    status.className = "muted small";
    status.textContent = "Undo checks restored accepted source. Newer work or changed inputs can block it.";
    const entries = document.createElement("div");
    const older = document.createElement("button");
    older.type = "button";
    older.textContent = "Load older resplits";
    older.hidden = true;
    panel.append(heading, status, entries, older);
    let cursor = null;
    const page = async () => {
      older.disabled = true;
      try {
        const report = await load(cursor);
        if (panel.historyToken !== token) return;
        if (!report.history.length && cursor === null) status.textContent = "No saved resplits yet.";
        for (const item of report.history) {
          const row = document.createElement("div");
          row.className = "small";
          const summary = item.summary;
          const text = document.createElement("span");
          text.textContent = `Split ${item.id}: ${summary.kept} unchanged, ${summary.added} added, ` +
            `${summary.removed} removed; ${summary.archived_attempts} attempts and ` +
            `${summary.archived_documented} documented routines retained in history. ` +
            (item.undone_at ? "Undone." : "");
          if (summary.profile_transition) {
            const change = summary.profile_transition;
            text.textContent += ` Profile: ${change.before.mapper} → ${change.proposed.mapper}; ` +
              `${change.proposed.variant}. `;
          }
          row.append(text);
          if (item.id === report.latest_active_id) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "ghost small-btn";
            button.textContent = "Undo this resplit";
            button.onclick = async () => {
              button.disabled = true;
              try { await undo(item.id); }
              catch (error) { status.textContent = error.message; }
              finally { button.disabled = false; }
            };
            row.append(button);
          }
          if (archive) {
            const browse = document.createElement("button"), saved = document.createElement("div");
            browse.type = "button";
            browse.textContent = "Browse saved work";
            browse.onclick = () => {
              browse.disabled = true;
              window.ResplitArchiveUI.render(saved, params => archive(item.id, params),
                () => panel.historyToken === token && panel.isConnected && !panel.hidden);
            };
            row.append(browse, saved);
          }
          entries.append(row);
        }
        cursor = report.next_before;
        older.hidden = cursor === null;
      } catch (error) { if (panel.historyToken === token) status.textContent = error.message; }
      finally { older.disabled = false; }
    };
    older.onclick = page;
    await page();
  },
  changes(panel, report) {
    if (!report.changed_work) return;
    const checks = document.createElement("p");
    checks.className = "muted small";
    const result = report.source_revalidation;
    checks.textContent = result ? `Source checks: ${result.passed} passed, ${result.failed} failed, ` +
      `${result.unresolved} unresolved. Failed/unresolved source remains unaccepted; retained interpretation needs review.` :
      `${report.source_revalidation_pending || 0} accepted sources need checks against the proposed layout on apply.`;
    panel.append(checks);
    const summary = document.createElement("p");
    summary.className = "muted small";
    summary.textContent = `Showing ${report.changed_work.length} of ${report.changed_work_count} changed routines. ` +
      "Removed work is retained in a private snapshot when this SMS/GG resplit is applied.";
    const list = document.createElement("ul");
    for (const item of report.changed_work) {
      const row = document.createElement("li");
      row.textContent = `${item.name}: ${item.action}; ${item.overlap_count} overlapping candidates` +
        (item.requires_revalidation ? "; accepted source needs revalidation." : ".");
      list.append(row);
    }
    panel.append(summary, list);
  }
};
