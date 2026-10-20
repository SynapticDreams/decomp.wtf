/* Batch controls share the existing helper/model catalogue. No credentials enter batch requests. */
"use strict";
window.ReviewBatchUI = {
  render(panel, batch, openFunction, resume, stop) {
    panel.replaceChildren(); panel.hidden = !batch;
    if (!batch) return;
    const line = (text, cls = "small") => { const p = document.createElement("p"); p.className = cls; p.textContent = text; panel.append(p); };
    line(`AI review batch · ${batch.state}`, "col-title");
    const c = batch.counts || {};
    line(`${c.reviewed || 0} reviewed · ${c.corrected || 0} corrected · ${c.needs_evidence || 0} need evidence · ${c.needs_layout || 0} need layout investigation · ${c.failed || 0} failed`);
    line(`${batch.sessions} / ${batch.limits.sessions} helper sessions · ${(batch.tokens || 0).toLocaleString()} reported tokens${batch.current ? ` · working on ${batch.current}` : ""}`);
    if (batch.reason) line(batch.reason);
    if (c.outdated) line(`${c.outdated} results have changed context; resume to review them again.`);
    const controls = document.createElement("div"); controls.className = "row";
    const button = document.createElement("button"); button.type = "button"; button.className = "ghost small-btn";
    if (batch.state === "running") { button.textContent = "Stop review batch"; button.onclick = stop; controls.append(button); }
    else if (batch.state === "paused" || c.outdated) { button.textContent = "Resume review batch…"; button.onclick = resume; controls.append(button); }
    panel.append(controls);
    const labels = {reviewed:"Reviewed", corrected:"Corrected", needs_evidence:"Needs evidence", needs_layout:"Needs layout investigation", failed:"Failed"};
    const details = document.createElement("details"), title = document.createElement("summary");
    title.textContent = `Results and saved follow-ups (${batch.total})`; details.append(title);
    const list = document.createElement("ul");
    for (const item of batch.items || []) {
      const li = document.createElement("li"), link = document.createElement("button");
      link.type = "button"; link.className = "link-btn mono"; link.textContent = item.name; link.onclick = () => openFunction(item.name);
      li.append(link, document.createTextNode(` · ${labels[item.status] || item.status}${item.outdated ? " · previous context" : ""}`));
      if (item.message) { const p = document.createElement("p"); p.className = "small"; p.textContent = item.message; li.append(p); }
      list.append(li);
    }
    details.append(list); panel.append(details);
    line("Human-review flags remain separate. Missing evidence and layout changes are saved for follow-up.");
  },
  open({slug, state, settings, agents, models, efforts, dialog, api, onUpdate, resume = false}) {
    const choices = [
      ...(settings.endpoints || []).map((ep) => ({key:`ep:${ep.id}`, name:`${ep.name} · ${ep.model}`, kind:"api", endpoint:ep.id})),
      ...(agents || []).filter((a) => a.installed && a.id !== "api").map((a) => ({key:`k:${a.id}`, name:a.name, kind:a.id, agent:a})),
    ];
    if (!choices.length) { dialog("Review remaining", '<p>Add an API endpoint or install a helper in Agents &amp; models first.</p>'); return; }
    const body = dialog(resume ? "Resume review batch" : "Review remaining", `<p class="muted">Review flagged routines, reuse current reports and save unresolved findings automatically. One helper runs at a time. Choose different writer and reviewer models for another perspective. Comment corrections are validated and independently reviewed before being applied. Instructions, names, layout and mapping stay protected.</p>
      <section id="batchReviewer"><h3>Reviewer</h3></section><section id="batchWriter"><h3>Comment writer</h3></section>
      <label class="check"><input type="checkbox" id="batchFix" checked><span>Automatically correct comments after validation and independent review</span></label>
      <label class="field"><span>Maximum routines</span><input id="batchFunctions" type="number" min="1" max="500"></label>
      <label class="field"><span>Maximum helper sessions</span><input id="batchSessions" type="number" min="1" max="1000"></label>
      <label class="field"><span>Time limit in minutes</span><input id="batchMinutes" type="number" min="1" max="240"></label>
      <label class="field"><span>Reported token limit</span><input id="batchTokens" type="number" min="1000" max="100000000"></label>
      <p class="muted small">Subscription/API usage applies. Resume grants a new allowance. Reported token counts can omit CLI usage and can overshoot during a request. The time limit stops the active batch helper. Each routine gets one correction cycle; unresolved findings remain saved.</p>
      <p class="small" id="batchError" role="alert" hidden></p><button class="primary" type="button" id="batchStart">${resume ? "Resume" : "Start batch"}</button>`);
    const el = (id) => body.querySelector(`#${id}`);
    const option = (select, value, text) => { const o = document.createElement("option"); o.value = value; o.textContent = text; select.append(o); };
    const picker = (prefix, saved, fallback) => {
      const section = el(prefix), who = document.createElement("select"), model = document.createElement("select"), custom = document.createElement("input"), effort = document.createElement("select");
      who.id = `${prefix}Who`; model.id = `${prefix}Model`; custom.id = `${prefix}Custom`; effort.id = `${prefix}Effort`;
      for (const [label, control] of [["Helper",who],["Model",model],["Custom model",custom],["Effort",effort]]) {
        const field = document.createElement("label"), title = document.createElement("span"); field.className = "field"; title.textContent = label; field.append(title,control); section.append(field);
      }
      for (const c of choices) option(who,c.key,c.name);
      const key = saved?.kind === "api" ? `ep:${saved.endpoint}` : saved?.kind ? `k:${saved.kind}` : fallback?.who;
      if (choices.some((c) => c.key === key)) who.value = key;
      const choice = () => choices.find((c) => c.key === who.value);
      const fillEffort = () => {
        effort.replaceChildren();
        for (const o of choice().agent ? efforts(choice().agent, model.value === "__other" ? custom.value : model.value) : []) option(effort,o.id,o.name);
        effort.closest("label").hidden = effort.options.length < 2;
        if (saved?.effort && [...effort.options].some((o) => o.value === saved.effort)) effort.value = saved.effort;
      };
      const syncCustom = () => { custom.closest("label").hidden = model.value !== "__other" || !choice().agent; fillEffort(); };
      const fillModel = () => {
        const c = choice(); model.replaceChildren();
        model.closest("label").hidden = !c.agent;
        const chosen = saved?.model || fallback?.setups?.[c.kind]?.model || "";
        for (const o of c.agent ? models(c.agent).filter((m) => m.id !== "tiered") : []) option(model,o.id,o.name);
        option(model,"__other","Another model…");
        model.value = [...model.options].some((o) => o.value === chosen) ? chosen : "__other";
        custom.value = model.value === "__other" ? chosen : "";
        syncCustom();
      };
      who.onchange = fillModel; model.onchange = syncCustom; custom.oninput = fillEffort; fillModel();
      return {setEnabled: (enabled) => { section.hidden = !enabled; }, value: () => {
        const c = choice(); return c.endpoint ? {kind:"api",endpoint:c.endpoint} : {kind:c.kind,
          model:model.value === "__other" ? custom.value.trim() : model.value, effort:effort.value};
      }};
    };
    const reviewer = picker("batchReviewer", state?.reviewer, settings.review_helper);
    const writer = picker("batchWriter", state?.writer, settings.pin_helper);
    el("batchFix").checked = state ? state.fix_comments : true;
    el("batchFix").onchange = () => writer.setEnabled(el("batchFix").checked); writer.setEnabled(el("batchFix").checked);
    const limits = {functions:100,sessions:100,minutes:30,tokens:1000000,...state?.limits};
    for (const [key, id] of [["functions","Functions"],["sessions","Sessions"],["minutes","Minutes"],["tokens","Tokens"]]) el(`batch${id}`).value = limits[key];
    el("batchStart").onclick = async () => {
      const start = el("batchStart"); start.disabled = true; el("batchError").hidden = true;
      try {
        const result = await api("/api/documented/batch", {method:"POST",body:{slug,action:resume?"resume":"start",reviewer:reviewer.value(),
          writer:el("batchFix").checked?writer.value():reviewer.value(),fix_comments:el("batchFix").checked,
          limits:{functions:Number(el("batchFunctions").value),sessions:Number(el("batchSessions").value),minutes:Number(el("batchMinutes").value),tokens:Number(el("batchTokens").value)}}});
        document.getElementById("dialog").hidden = true; onUpdate(result);
      } catch (e) { el("batchError").textContent = e.message; el("batchError").hidden = false; start.disabled = false; }
    };
  },
};
