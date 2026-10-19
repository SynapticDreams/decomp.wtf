"use strict";
/* Read-only recovery. Text is copied/downloaded only after complete, digest-checked retrieval. */
window.ResplitArchiveUI = {
  async render(panel, load, active = () => true) {
    const renderToken = Symbol();
    panel.archiveToken = renderToken;
    const isActive = () => panel.archiveToken === renderToken && panel.isConnected && active();
    panel.replaceChildren();
    const el = (tag, text, parent = panel) => {
      const node = document.createElement(tag);
      if (text !== undefined) node.textContent = text;
      parent.append(node);
      return node;
    };
    const button = (text, parent, action) => {
      const node = el("button", text, parent);
      node.type = "button";
      node.onclick = action;
      return node;
    };
    el("p", "Saved work is a reference. Review copied source and submit it through the usual source checks.");
    const status = el("p", "");
    status.setAttribute("role", "status");
    const functions = el("div"), details = el("div"), viewer = el("div");
    let version = 0, itemVersion = 0, cursor = 0, projectShown = false;
    const current = token => isActive() && token === version;
    const showItem = async (selection, key) => {
      const token = version, selected = ++itemVersion;
      const alive = () => current(token) && selected === itemVersion;
      viewer.replaceChildren();
      const description = el("pre", "", viewer), text = el("textarea", "", viewer);
      text.readOnly = true;
      text.rows = 12;
      text.setAttribute("aria-label", "Saved text");
      const actions = el("div", undefined, viewer);
      const complete = button("Load complete text", actions, () => retrieve(true));
      const copy = button("Copy text", actions, async () => {
        try { await navigator.clipboard.writeText(verifiedText); if (alive()) status.textContent = "Copied saved text."; }
        catch (error) { if (alive()) status.textContent = error.message; }
      });
      const save = (body, name, type) => {
        const url = URL.createObjectURL(new Blob([body], { type }));
        const link = document.createElement("a");
        link.href = url;
        link.download = name;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      };
      const download = button("Download text", actions, () => save(verifiedText, filename, "text/plain;charset=utf-8"));
      const record = button("Download with provenance", actions, () => save(JSON.stringify({ ...provenance, text: verifiedText }, null, 2),
        `${filename}.json`, "application/json"));
      copy.disabled = download.disabled = record.disabled = complete.disabled = true;
      let provenance = null, verifiedText = "";
      let next = 0, total = null, digest = null, filename = "saved.txt", chunks = [];
      async function retrieve(all) {
        complete.disabled = true;
        try {
          do {
            const part = await load({ ...selection, item: key, start: next, limit: all ? 262144 : 16384 });
            if (!alive()) return;
            if (part.start !== next || (total !== null && (total !== part.characters || digest !== part.sha256)) ||
                part.characters > 67108864 || (part.next_start !== null && part.next_start <= next)) {
              throw new Error("Saved text changed or returned an invalid chunk.");
            }
            total = part.characters; digest = part.sha256; filename = part.filename;
            chunks.push(part.text); next = part.next_start;
            provenance = { origin: part.origin, function: part.function, project_context: part.project_context,
              item: part.item, sha256: part.sha256 };
            description.textContent = JSON.stringify(provenance, null, 2);
            status.textContent = next === null ? "Checking complete saved text…" : `Loaded ${next} of ${total} characters.`;
          } while (all && next !== null);
          const body = chunks.join("");
          text.value = body;
          if (next === null) {
            const bytes = new TextEncoder().encode(body);
            const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), b => b.toString(16).padStart(2, "0")).join("");
            if (!alive()) return;
            let characters = 0;
            for (const _ of body) ++characters;
            if (hash !== digest || characters !== total) throw new Error("Saved text digest or length differs.");
            verifiedText = body;
            copy.disabled = download.disabled = record.disabled = false;
            complete.hidden = true;
            status.textContent = "Complete saved text verified. Copy or download it for review.";
          }
        } catch (error) {
          if (alive()) { status.textContent = error.message; next = null; complete.hidden = true; }
        } finally { if (alive()) complete.disabled = next === null; }
      }
      await retrieve(false);
    };
    const showSubject = async selection => {
      const token = ++version;
      ++itemVersion;
      details.replaceChildren(); viewer.replaceChildren();
      let offset = 0;
      const entries = el("div", undefined, details);
      const more = button("Load more saved items", details, () => page());
      const page = async () => {
        more.disabled = true;
        try {
          const result = await load({ ...selection, offset });
          if (!current(token)) return;
          for (const entry of result.items) button(entry.label, entries, () => showItem(selection, entry.key));
          offset = result.next_offset; more.hidden = offset === null;
          status.textContent = `${(result.function || result.project_context).name}: ${result.total} saved sources, notes and context records.`;
        } catch (error) { if (current(token)) status.textContent = error.message; }
        finally { if (current(token)) more.disabled = false; }
      };
      await page();
    };
    const more = button("Load more saved functions", functions, () => page());
    const page = async () => {
      more.disabled = true;
      try {
        const result = await load({ offset: cursor });
        if (!isActive()) return;
        if (result.project_context_available && !projectShown) {
          projectShown = true;
          button("Saved project context", functions, () => showSubject({ scope: "project" }));
        }
        for (const fn of result.functions) {
          const row = document.createElement("p");
          functions.insertBefore(row, more);
          button(`${fn.name} (${fn.status}; ROM ${fn.rom_offset}, CPU ${fn.vram})`, row, () => showSubject({ function: fn.id }));
        }
        cursor = result.next_offset; more.hidden = cursor === null;
        if (!version) status.textContent = `${result.total} saved functions. Select project context or a function to inspect saved work.`;
      } catch (error) { if (isActive()) status.textContent = error.message; }
      finally { more.disabled = false; }
    };
    await page();
  }
};
