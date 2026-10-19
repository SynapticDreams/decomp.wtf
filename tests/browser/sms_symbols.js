/* Authored files and API responses exercise the real operator component and markup. */
(async () => {
  const assert = (value, why) => { if (!value) throw new Error(why); };
  const root = document.getElementById("smsSymbols");
  const node = key => root.querySelector(`[data-symbol="${key}"]`);
  const calls = [], notices = [];
  let slug = "sms-a", metadata = null, failApply = false, failPage = false, hold = null, deferred = false;
  let activeContext = "authored-context";
  let started;
  const requestStarted = new Promise(resolve => { started = resolve; });
  let ui;
  const overview = () => ({ slug, sms_progress: {} });
  const report = (offset = 0, declared = true, source = "saved-a") => ({
    state: declared ? "declared" : "requires_layout", names: declared ? 1 : 0, seeds: declared ? 2 : 0,
    alias_count: declared ? 1 : 0, record_count: 51, offset, next_offset: offset ? null : 50,
    source_id: source, inspection_context: activeContext, source: { sha256: "authored-source-sha" }, input: { sha256: "authored-input-sha" },
    counts: { code: 1, ambiguous_view: 1 }, records: [{ line: offset + 1, bank: 1, cpu: 0x2100,
      name: offset ? "SecondPageAlias" : "<img src=x>", status: "ambiguous_view",
      coordinates: [{ slot: 1, space: "rom", rom_offset: 0x2100, physical_bank: 0 }] }]
  });
  const api = async (path, options) => {
    const body = options.body;
    calls.push({ path, body });
    if (path.endsWith("/remove")) { metadata = null; return {}; }
    if (path.endsWith("/inspect")) {
      if (failPage && body.offset) throw new Error("symbol source changed; inspect again");
      return report(body.offset || 0);
    }
    if (body.apply) {
      if (failApply) throw new Error("symbol preview is stale; preview again");
      metadata = { state: "declared", source_id: "saved-a", names: 1 };
      return { applied: true, symbol_file: metadata };
    }
    const result = { plan: "authored-plan", symbol_file: report(body.offset || 0, !!body.layout, "preview-a") };
    if (deferred) return new Promise(resolve => { hold = () => resolve(result); started(); });
    return result;
  };
  const choose = (key, files) => {
    const data = new DataTransfer();
    for (const file of files) data.items.add(file);
    node(key).files = data.files;
    node(key).onchange();
  };
  const bytes = new Uint8Array([239, 187, 191, 59, 32, 112, 114, 105, 118, 97, 116, 101, 13, 10]);
  const source = new File([bytes], "authored.sym"), layout = new File(['{"version":1}'], "layout.json");
  try {
    ui = window.SMSSymbolUI.create(root, { api, getSlug: () => slug,
      refresh: async () => ui.render(overview(), metadata), notify: message => notices.push(message) });
    ui.render(overview(), null);
    assert(node("apply").disabled && node("inspect").disabled, "no source starts with no applicable preview");
    choose("source", [source]); choose("layout", [layout]);
    await node("preview").onclick();
    const first = calls.at(-1).body;
    assert(first.slug === "sms-a" && first.apply === false && first.layout.version === 1, "preview carries its captured project and declaration");
    assert([...atob(first.source_base64)].map(c => c.charCodeAt(0)).join() === [...bytes].join(), "BOM and CRLF bytes are preserved");
    assert(root.textContent.includes("candidate names") && root.textContent.includes("meanings remain unreviewed"), "labels never establish semantic approval");
    assert(root.textContent.includes("source 0001:2100") && root.textContent.includes("ROM $002100 (physical bank 0)"), "assembler and physical coordinates are distinct");
    assert(!root.querySelector("img") && root.textContent.includes("<img src=x>"), "records render as escaped text");
    await node("more").onclick();
    assert(calls.at(-1).body.offset === 50 && calls.at(-1).body.expected_plan === "authored-plan", "preview pages retain their lease");
    assert(node("records").textContent.includes("SecondPageAlias") && !node("records").textContent.includes("<img"), "pages replace rather than accumulate records");
    await node("apply").onclick();
    assert(calls.at(-1).body.apply && calls.at(-1).body.expected_plan === "authored-plan" && !calls.at(-1).body.offset, "application uses the reviewed source and first-page lease");
    assert(node("apply").disabled && notices.length === 1, "a used preview cannot be applied again");
    await node("inspect").onclick(); await node("more").onclick();
    assert(calls.at(-1).body.expected_source === "saved-a", "stored pages retain their source identity");
    assert(calls.at(-1).body.expected_context === "authored-context", "stored pages retain their mapper/project context");
    activeContext = "changed-context";
    metadata = { ...metadata, inspection_context: activeContext };
    ui.render(overview(), metadata);
    assert(!node("records").textContent && node("more").hidden, "a context change clears old pages even when source bytes stay the same");
    await node("inspect").onclick(); failPage = true; await node("more").onclick();
    assert(node("status").textContent.includes("source changed") && node("more").hidden, "changed sources cannot mix inspection pages");
    failPage = false;
    await node("preview").onclick(); failApply = true; await node("apply").onclick();
    assert(node("apply").disabled && node("status").textContent.includes("preview is stale"), "failed leases require a new preview");
    failApply = false;
    choose("layout", []); await node("preview").onclick();
    assert(node("apply").textContent === "Store pending source" && node("status").textContent.includes("0 seed suggestions"), "undeclared sources stay pending");
    choose("layout", [new File(['null'], "bad.json")]);
    const before = calls.length;
    await node("preview").onclick();
    assert(calls.length === before && node("apply").disabled, "invalid declarations never reach application");
    choose("layout", [layout]);
    deferred = true;
    const old = node("preview").onclick();
    await requestStarted;
    assert(hold, "the old request is confirmed in flight");
    slug = "gg-b"; ui.render(overview(), null); hold(); await old;
    assert(node("apply").disabled && !node("records").textContent && !node("source").files.length,
      "a project switch clears files, previews and late replies");
    deferred = false;
    ui.render({ slug: "gb-a", platform: "gb" }, null);
    assert(root.hidden, "non-SMS projects keep their own symbol flow");
    document.getElementById("report").textContent = "PASS: source bytes, coordinates, leases, paging, pending states and project switches";
  } catch (error) { document.getElementById("report").textContent = "FAIL: " + error.stack; }
})();
