/* Authored interaction checks against the actual profile component and DOM. */
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
  const preview = () => button("Preview profile and resplit");
  const apply = () => button("Apply profile and resplit");
  let active = true, resolve = null, fail = false, applied = 0, saves = 0;
  const view = { message: "Authored fixture", supported_mappers: ["sega", "mapperless", "codemasters"],
    profile: { mapper: "sega", variant: "annotated-original", reason: "Independently authored fixture evidence." } };
  const report = { plan: "a".repeat(64), before: 2, after: 2, added: 0, removed: 0,
    profile_transition: { before: { mapper: "sega" }, proposed: { mapper: "mapperless" } },
    source_revalidation_pending: 1, changed_work: [], changed_work_count: 0 };
  const render = () => window.SMSProfileUI.render(panel, view, async () => { saves++; }, null, {
    current: () => active,
    run: (choice, commit, plan) => {
      requests.push({ choice, commit, plan });
      if (fail) return Promise.reject(new Error("<img src=x> stale fixture proposal"));
      return new Promise(done => { resolve = () => done(report); });
    }, applied: async () => { applied++; }
  });
  const finish = async () => { resolve(); await wait(() => !preview().disabled); };
  try {
    render();
    panel.querySelector("select").value = "mapperless";
    assert(apply().hidden, "apply requires a preview");
    preview().click();
    assert(requests[0].choice.mapper === "mapperless" && !requests[0].commit && requests[0].plan === null,
      "preview sends an immutable proposed profile");
    const reason = panel.querySelector("textarea");
    reason.value += " Edited while preview ran.";
    reason.dispatchEvent(new Event("input", { bubbles: true }));
    await finish();
    assert(apply().hidden, "editing invalidates a pending preview");
    preview().click(); await finish();
    assert(!apply().hidden && panel.textContent.includes("1 accepted sources"), "fresh preview shows checks and apply");
    panel.querySelector("select").value = "codemasters";
    apply().click();
    assert(apply().hidden && requests.length === 2, "changed choices cannot use an old fingerprint");
    preview().click(); await finish();
    apply().click();
    assert(requests[3].commit && requests[3].plan === report.plan && requests[3].choice.mapper === "codemasters",
      "apply sends the exact previewed proposal and fingerprint");
    assert(panel.querySelector("textarea").disabled, "proposal controls are locked during apply");
    await finish();
    assert(applied === 1 && apply().hidden && !reason.disabled, "apply refreshes once and consumes its lease");
    fail = true;
    preview().click(); await wait(() => !preview().disabled);
    assert(panel.textContent.includes("stale fixture proposal") && !panel.querySelector("img") && apply().hidden,
      "errors render as text and never unlock apply");
    fail = false;
    preview().click(); active = false; await finish();
    assert(apply().hidden, "project change discards a late preview");
    active = true;
    preview().click(); const oldResolve = resolve;
    render(); oldResolve(); await new Promise(done => setTimeout(done, 5));
    assert(apply().hidden && !panel.textContent.includes("Proposed mapper"), "rerender discards old responses");
    button("Save cartridge profile").click(); await wait(() => saves === 1);
    assert(requests.length === 7 && applied === 1, "ordinary profile saves remain separate");
    document.getElementById("report").textContent = "PASS: profile preview/apply, edits, errors and stale project responses";
  } catch (error) { document.getElementById("report").textContent = "FAIL: " + error.stack; }
})();
