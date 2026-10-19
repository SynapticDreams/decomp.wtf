/* Authored preview records, rendered by the actual history/inspection/profile components. */
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
  const coordinate = i => ({ rom_offset: 8192 + i * 8, cpu: 8192 + i * 8, size: 3 });
  const rows = Array.from({ length: 130 }, (_, i) => ({ id: i + 1, name: i ? `Entry${i}` : "<img src=x>",
    ...coordinate(i), status: "documented", overlap_count: i ? 0 : 130 }));
  const report = { inspection_available: true, plan: "b".repeat(64), changed_work_count: 130,
    changed_work_truncated: true, changed_work: rows.slice(0, 100), source_revalidation_pending: 130,
    source_revalidation_limits: { functions: 32, seconds: 30 }, before: 130, after: 132, added: 132, removed: 130,
    profile_transition: { before: { mapper: "sega" }, proposed: { mapper: "mapperless" } } };
  let active = true, invalidated = 0, resolve = null, defer = false, wrongPlan = false, fail = false;
  const response = selection => {
    const all = selection.kind === "overlaps" ? rows.map((_, i) => coordinate(i)) :
      selection.kind === "checks" ? rows.map(row => ({ ...row, proposed: null })) : rows;
    const end = selection.offset + 100;
    return { plan: wrongPlan ? "c".repeat(64) : report.plan, inspection: { ...selection, limit: 100,
      function: { id: selection.function }, total: all.length, rows: all.slice(selection.offset, end),
      next_offset: end < all.length ? end : null } };
  };
  const load = async selection => {
    requests.push(selection);
    if (fail) throw new Error("<img src=x> preview is stale");
    if (defer) return new Promise(done => { resolve = () => done(response(selection)); });
    return response(selection);
  };
  const render = () => {
    panel.replaceChildren();
    window.ResplitHistoryUI.changes(panel, report, load, () => active, () => { invalidated++; });
  };
  try {
    render();
    assert(panel.textContent.includes("1–100 of 130") && !panel.querySelector("img"), "bounded first page renders text");
    button("Next changed routines").click();
    await wait(() => panel.textContent.includes("101–130 of 130"));
    assert(!panel.textContent.includes("Entry1:") && panel.textContent.includes("Entry129:"), "next replaces previous records");
    button("Previous changed routines").click();
    await wait(() => !!button("Inspect overlaps for 1"));
    button("Inspect overlaps for 1").click();
    await wait(() => !!button("Next overlaps for 1") && !button("Next overlaps for 1").disabled);
    button("Next overlaps for 1").click();
    await wait(() => panel.textContent.includes("overlaps for 1: 101–130"));
    assert(requests.some(r => r.kind === "overlaps" && r.offset === 100 && r.function === 1), "all overlaps are inspectable");
    button("Inspect accepted source checks").click();
    await wait(() => !!button("Next accepted source checks") && !button("Next accepted source checks").disabled);
    button("Next accepted source checks").click();
    await wait(() => panel.textContent.includes("accepted source checks: 101–130"));
    assert(panel.textContent.includes("No proposed entry") && panel.textContent.includes("32-function / 30-second"),
      "checks and automatic limits remain visible");
    wrongPlan = true;
    button("Previous changed routines").disabled = false;
    button("Previous changed routines").click();
    await wait(() => invalidated === 1);
    assert(panel.textContent.includes("Preview inspection changed") && !button("Next changed routines"), "mixed plans invalidate apply");
    wrongPlan = false; fail = true; render();
    button("Next changed routines").click(); await wait(() => invalidated === 2);
    assert(panel.textContent.includes("preview is stale") && !panel.querySelector("img"), "server errors invalidate and escape text");
    fail = false; defer = true; render();
    button("Next changed routines").click(); active = false; resolve();
    await new Promise(done => setTimeout(done, 5));
    assert(!panel.textContent.includes("101–130") && invalidated === 2, "project switches discard responses");
    active = true; render(); button("Next changed routines").click(); const oldResolve = resolve;
    render(); oldResolve(); await new Promise(done => setTimeout(done, 5));
    assert(!panel.textContent.includes("101–130"), "rerender discards detached page responses");
    defer = false;
    const migrationRequests = [];
    window.SMSProfileUI.render(panel, { message: "Authored", supported_mappers: ["sega", "mapperless"],
      profile: { mapper: "mapperless", variant: "annotated-original", reason: "Authored independent evidence." } }, async () => {}, null, {
      current: () => active, applied: async () => {}, run: async (choice, commit, plan, log, selection) => {
        migrationRequests.push({ choice, commit, plan, selection });
        if (!selection) return report;
        return new Promise(done => { resolve = () => done(response(selection)); });
      }
    });
    button("Preview profile and resplit").click();
    await wait(() => !button("Apply profile and resplit").hidden);
    button("Inspect accepted source checks").click();
    assert(migrationRequests[1].choice.mapper === "mapperless" && migrationRequests[1].plan === report.plan &&
      migrationRequests[1].selection.kind === "checks", "migration inspection binds its original proposal and plan");
    const reason = panel.querySelector("textarea");
    reason.value += " Edited."; reason.dispatchEvent(new Event("input", { bubbles: true })); resolve();
    await new Promise(done => setTimeout(done, 5));
    assert(button("Apply profile and resplit").hidden && !panel.textContent.includes("accepted source checks:"),
      "editing the migration discards pending pages and its apply lease");
    document.getElementById("report").textContent = "PASS: all preview pages, overlaps, checks and stale guards";
  } catch (error) { document.getElementById("report").textContent = "FAIL: " + error.stack; }
})();
