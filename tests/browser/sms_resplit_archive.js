/* Authored browser behavior checks; loaded with the actual archive/history UI modules. */
(async () => {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const wait = async condition => {
    for (let i = 0; i < 200; i++) {
      if (condition()) return;
      await new Promise(resolve => setTimeout(resolve, 1));
    }
    throw new Error("browser condition did not complete");
  };
  const button = text => Array.from(document.querySelectorAll("button")).find(node => node.textContent === text);
  const digest = async text => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))),
    b => b.toString(16).padStart(2, "0")).join("");
  const panel = document.getElementById("panel");
  const source = "authored text\r\n".repeat(2000) + "😀 <img src=x onerror=alert(1)> complete";
  let copied = null, downloaded = null, sourceWait = null, functionWait = null, deferSource = false, deferFunction = false;
  let badDigest = false, missing = false, active = true;
  const requests = [];
  Object.defineProperty(navigator, "clipboard", { value: { writeText: async text => { copied = text; } } });
  URL.createObjectURL = blob => { downloaded = blob; return "blob:fixture"; };
  URL.revokeObjectURL = () => {};
  HTMLAnchorElement.prototype.click = function () {};
  const chunk = async params => {
    const text = params.item === "accepted" ? source : params.item === "best" ? "newer authored reference 😀" : "authored note";
    const points = Array.from(text), end = params.start + params.limit;
    return { text: points.slice(params.start, end).join(""), start: params.start,
      next_start: end < points.length ? end : null, characters: points.length, sha256: badDigest ? "invalid" : await digest(text),
      filename: "function_1_accepted.c", origin: { history_id: 7, snapshot_sha256: "fixture" },
      function: { id: params.function }, item: { key: params.item } };
  };
  const load = async params => {
    requests.push(params);
    if (params.item) {
      if (missing) throw new Error("saved fixture is unavailable");
      const result = await chunk(params);
      if (deferSource && params.item === "accepted") return new Promise(resolve => { sourceWait = () => resolve(result); });
      return result;
    }
    if (params.function) {
      const result = { function: { name: `Function ${params.function}` }, total: 3,
        items: params.offset ? [{ key: "note:1", label: "Saved note" }] :
          [{ key: "accepted", label: "Previously accepted source" }, { key: "best", label: "Saved best source" }],
        next_offset: params.offset ? null : 25 };
      if (deferFunction && params.function === 2) return new Promise(resolve => {
        functionWait = () => resolve({ ...result, items: [{ key: "best", label: "STALE RESPONSE" }] });
      });
      return result;
    }
    return { total: 2, functions: [{ id: params.offset ? 2 : 1, name: params.offset ? "Function B" : "<img src=x onerror=alert(1)>",
      status: "matched", rom_offset: 512, vram: 512 }], next_offset: params.offset ? null : 25 };
  };
  try {
    await ResplitArchiveUI.render(panel, load, () => active);
    assert(!panel.querySelector("img"), "function names must be text");
    button("Load more saved functions").click();
    await wait(() => requests.some(request => request.offset === 25 && !request.function));
    await wait(() => Array.from(panel.querySelectorAll("button")).some(node => node.textContent.startsWith("Function B")));
    const choose = prefix => Array.from(panel.querySelectorAll("button")).find(node => node.textContent.startsWith(prefix)).click();
    choose("<img");
    await wait(() => button("Previously accepted source"));
    button("Previously accepted source").click();
    await wait(() => button("Load complete text") && !button("Load complete text").disabled);
    assert(button("Copy text").disabled && button("Download text").disabled, "partial source cannot be exported as complete");
    button("Load complete text").click();
    await wait(() => !button("Copy text").disabled);
    assert(panel.querySelector("textarea").value === source.replaceAll("\r\n", "\n") && !panel.querySelector("img"), "Unicode/source text must round trip safely");
    button("Copy text").click();
    await wait(() => copied === source);
    button("Download with provenance").click();
    const record = JSON.parse(await downloaded.text());
    assert(record.text === source && record.origin.history_id === 7 && record.sha256 === await digest(source), "download must retain provenance");
    button("Load more saved items").click();
    await wait(() => button("Saved note"));
    assert(requests.some(request => request.function === 1 && request.offset === 25), "item pagination must remain usable after viewing a source");
    deferSource = true;
    button("Previously accepted source").click();
    await wait(() => sourceWait);
    button("Saved best source").click();
    await wait(() => !button("Copy text").disabled);
    sourceWait();
    await new Promise(resolve => setTimeout(resolve, 10));
    assert(panel.querySelector("textarea").value.startsWith("newer authored"), "stale item response cannot replace selected text");
    deferSource = false;
    badDigest = true;
    button("Saved note").click();
    await wait(() => panel.textContent.includes("digest or length differs"));
    assert(button("Copy text").disabled && button("Download with provenance").disabled, "digest failures cannot enable recovery buttons");
    badDigest = false;
    missing = true;
    button("Saved note").click();
    await wait(() => panel.textContent.includes("saved fixture is unavailable"));
    assert(button("Copy text").disabled, "errors must remain visible without enabling export");
    missing = false;
    deferFunction = true;
    choose("Function B");
    await wait(() => functionWait);
    choose("<img");
    await wait(() => button("Previously accepted source"));
    functionWait();
    await new Promise(resolve => setTimeout(resolve, 10));
    assert(!panel.textContent.includes("STALE RESPONSE"), "stale function response cannot replace current items");
    let resolvePage;
    const pending = ResplitArchiveUI.render(panel, () => new Promise(resolve => { resolvePage = resolve; }), () => active);
    active = false;
    resolvePage({ total: 1, functions: [{ id: 1, name: "WRONG PROJECT" }], next_offset: null });
    await pending;
    assert(!panel.textContent.includes("WRONG PROJECT"), "changed projects must discard pending archive pages");
    await ResplitHistoryUI.render(panel, async () => ({ history: [{ id: 7, summary: { kept: 1, added: 0, removed: 1,
      archived_attempts: 1, archived_documented: 0 } }], next_before: null, latest_active_id: null }), async () => {},
      async (_id, params) => load(params));
    button("Browse saved work").click();
    await wait(() => panel.textContent.includes("2 saved functions"));
    document.getElementById("report").textContent = "PASS: paging, Unicode, copy/download, provenance, digest/errors and stale responses";
  } catch (error) { document.getElementById("report").textContent = `FAIL: ${error.stack}`; }
})();
