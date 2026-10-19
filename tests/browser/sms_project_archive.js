/* Authored empty-function project context, using the actual digest-checked archive UI. */
(async () => {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const wait = async condition => {
    for (let i = 0; i < 200; i++) {
      if (condition()) return;
      await new Promise(resolve => setTimeout(resolve, 1));
    }
    throw new Error("browser condition did not complete");
  };
  const panel = document.getElementById("panel"), requests = [];
  const button = text => Array.from(panel.querySelectorAll("button")).find(node => node.textContent === text);
  const text = "Authored project note\r\n".repeat(2000) + "😀 <img src=x> intact";
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))),
    b => b.toString(16).padStart(2, "0")).join("");
  let copied = null, downloaded = null, resolve = null, defer = false, active = true, badDigest = false;
  Object.defineProperty(navigator, "clipboard", { value: { writeText: async value => { copied = value; } } });
  URL.createObjectURL = value => { downloaded = value; return "blob:authored"; };
  URL.revokeObjectURL = () => {};
  HTMLAnchorElement.prototype.click = function () {};
  const context = { scope: "project", name: "Saved project context" };
  const load = async params => {
    requests.push(params);
    if (!params.scope) return { functions: [], project_context_available: true, total: 0, next_offset: null };
    assert(params.scope === "project" && params.function === undefined, "project requests never invent a function ID");
    if (!params.item) return { project_context: context, total: 28, next_offset: params.offset ? null : 25,
      items: params.offset ? [{ key: "note:99", label: "Saved final note" }] : [{ key: "note:17", label: "Saved note 17" }] };
    const points = Array.from(text), end = params.start + params.limit;
    const response = { project_context: context, origin: { history_id: 7, snapshot_sha256: "authored" },
      item: { key: params.item, provenance: { association: "project" } }, text: points.slice(params.start, end).join(""),
      start: params.start, characters: points.length, next_start: end < points.length ? end : null,
      sha256: badDigest ? "invalid" : digest, filename: "project_1_note_17.txt" };
    if (defer) return new Promise(done => { resolve = () => done(response); });
    return response;
  };
  const render = () => window.ResplitArchiveUI.render(panel, load, () => active);
  try {
    await render();
    assert(panel.textContent.includes("0 saved functions") && button("Saved project context"), "empty snapshot still exposes context");
    button("Saved project context").click(); await wait(() => !!button("Saved note 17"));
    button("Load more saved items").click(); await wait(() => !!button("Saved final note"));
    assert(requests.some(r => r.scope === "project" && r.offset === 25), "project item pagination uses its own scope");
    button("Saved note 17").click(); await wait(() => !!button("Load complete text") && !button("Load complete text").disabled);
    assert(button("Copy text").disabled, "partial project text cannot be copied");
    button("Load complete text").click(); await wait(() => !button("Copy text").disabled);
    button("Copy text").click(); await wait(() => copied !== null);
    assert(copied === text && !panel.querySelector("img"), "full Unicode and CRLF project text is preserved and escaped");
    button("Download with provenance").click();
    const record = JSON.parse(await downloaded.text());
    assert(record.text === text && record.project_context.scope === "project" && !record.function,
      "download carries project provenance without an invented function");
    badDigest = true;
    button("Saved note 17").click(); await wait(() => !button("Load complete text").disabled);
    button("Load complete text").click(); await wait(() => panel.textContent.includes("digest or length differs"));
    assert(button("Copy text").disabled, "invalid project text is not copyable");
    badDigest = false; defer = true;
    button("Saved note 17").click(); active = false; resolve();
    await new Promise(done => setTimeout(done, 5));
    assert(button("Copy text").disabled, "project changes discard pending text");
    active = true; button("Saved note 17").click(); const oldResolve = resolve;
    await render(); oldResolve(); await new Promise(done => setTimeout(done, 5));
    assert(!panel.querySelector("textarea") && !panel.textContent.includes("Loaded"), "rerenders discard old project text");
    document.getElementById("report").textContent = "PASS: project recovery, complete text, provenance and stale guards";
  } catch (error) { document.getElementById("report").textContent = "FAIL: " + error.stack; }
})();
