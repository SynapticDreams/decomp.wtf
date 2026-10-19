"use strict";
/* A proposal is saved only by the server's guarded profile/layout transaction. */
window.SMSProfileMigrationUI = {
  render(panel, read, run, current, applied, pending) {
    const controls = document.createElement("div");
    const preview = document.createElement("button"), apply = document.createElement("button");
    preview.type = apply.type = "button";
    preview.textContent = "Preview profile and resplit";
    apply.textContent = "Apply profile and resplit";
    apply.hidden = true;
    const result = document.createElement("div"), log = document.createElement("pre");
    log.className = "joblog";
    log.hidden = true;
    controls.append(preview, apply, result, log);
    panel.append(controls);
    let revision = 0, saved = null, busy = false;
    const reset = () => {
      revision++;
      saved = null;
      apply.hidden = true;
      result.replaceChildren();
    };
    panel.addEventListener("input", reset);
    panel.addEventListener("change", reset);
    const request = async (commit) => {
      if (busy || !current()) return;
      if (commit && (!saved || JSON.stringify(read()) !== JSON.stringify(saved.choice))) { reset(); return; }
      const choice = commit ? saved.choice : { ...read() };
      const plan = commit ? saved.plan : null;
      reset();
      const started = revision;
      busy = true;
      preview.disabled = apply.disabled = true;
      pending(true, commit);
      log.replaceChildren();
      log.hidden = false;
      try {
        const report = await run(choice, commit, plan, log);
        if (!current() || revision !== started) return;
        const status = document.createElement("p");
        const transition = report.profile_transition;
        status.textContent = `${commit ? "Applied" : "Proposed"} mapper: ${transition.before.mapper} → ` +
          `${transition.proposed.mapper}. ${report.before} → ${report.after} functions; ` +
          `${report.added} added, ${report.removed} removed. ` +
          "Accepted source is checked on apply; names and purposes still need review.";
        result.append(status);
        window.ResplitHistoryUI.changes(result, report,
          selection => run(choice, false, report.plan, null, selection),
          () => current() && revision === started && JSON.stringify(read()) === JSON.stringify(choice),
          () => { saved = null; apply.hidden = true; revision++; });
        if (commit) await applied();
        else if (/^[0-9a-f]{64}$/.test(report.plan)) {
          saved = { choice, plan: report.plan };
          apply.hidden = false;
        }
      } catch (error) {
        if (current() && revision === started) result.textContent = error.message;
      } finally {
        busy = false;
        preview.disabled = apply.disabled = false;
        pending(false, commit);
      }
    };
    preview.onclick = () => request(false);
    apply.onclick = () => request(true);
  }
};
