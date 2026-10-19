/* Authored responses deliberately interleave reads and previews. Real route compatibility is tested separately. */
(async () => {
  const assert = (value, why) => { if (!value) throw new Error(why); };
  const root = document.getElementById("smsResearch");
  const node = key => root.querySelector(`[data-research="${key}"]`);
  const field = key => root.querySelector(`[data-research-input="${key}"]`);
  const set = (key, value) => { field(key).value = value; field(key).dispatchEvent(new Event("input", { bubbles: true })); };
  const value = { version: 1, kind: "data", target: { space: "rom", offset: 256, size: 16 }, spec: { encoding: "bytes" } };
  const proof = { version: 1, revision: { sha256: "old-revision" }, context: { sha256: "old-context" }, subject_sha256: "old-subject",
    origin: { kind: "import", ref: "authored-source" }, state: "interpretation", confidence: "medium", alternatives: ["A competing explanation."],
    links: [{ kind: "external", ref: "https://example.invalid/reference", sha256: null }],
    review: { state: "accepted", actor: "claimed-operator", at: 1, binding_sha256: "claimed-receipt" } };
  const metadata = (v, status = "supported") => ({ status, value: status === "supported" ? structuredClone(v) : null, raw: JSON.stringify(v), truncated: false });
  const record = (subject, key, application = "pending_review") => ({ id: key, key, kind: subject, where: "00:0100", reason: "The authored consumer reads this bounded layout.",
    text: `Inspection ${key} <img src=x>`, symbol: { name: String(key), address: 256, size: 16, kind: "data" },
    application, binding: ["stale", "unavailable"].includes(application) ? application : "current", review: "untrusted", state: "interpretation", confidence: "medium", active: false, discovery: false,
    annotation: metadata(value), evidence: metadata(proof), subject: metadata({ entity: { text: "Original archived prose." } }) });
  let slug = "sms-a", subject = "correction", held = null, failApply = false, plan = 0;
  const calls = [];
  const overview = () => ({ slug, platform: slug.startsWith("gg") ? "gg" : "sms", kind: "rom", sms_progress: {}, sms_profile: { mapper: "sega" } });
  const defer = predicate => {
    let started;
    const gate = { predicate, started: new Promise(resolve => { started = resolve; }), signal: () => started() };
    held = gate;
    return gate;
  };
  const api = async (path, options) => {
    calls.push({ path, options: structuredClone(options) });
    const body = options?.body, query = new URL(path, "https://fixture.invalid").searchParams;
    const kind = path.startsWith("/api/corrections") ? "correction" : path.startsWith("/api/note") ? "note" : "symbol";
    let result;
    if (options?.method === "POST") {
      if (body.apply && failApply) throw new Error("project work changed; preview again");
      const item = record(kind, body.id || body.symbol || 77, body.apply ? body.action === "clear" ? "legacy_unknown" : "pending_review" : "pending_review");
      if (body.annotation) item.annotation = metadata(body.annotation);
      result = { applied: body.apply, plan: `plan-${++plan}`, decision: body.action === "review" ? "accepted" : body.action === "clear" ? "detach_metadata" : undefined,
        ...(kind === "correction" ? { correction: item } : { record: item }) };
    } else if (query.has("id") || query.has("symbol")) {
      const key = query.get("symbol") || Number(query.get("id"));
      const states = { 2: "unsupported", 3: "stale", 4: "unavailable", 5: "archived", 6: "untrusted_review", 7: "invalid", 8: "unsupported", 9: "unsupported" };
      result = record(kind, key, states[key] || "pending_review");
      if (key === 2 || key === 7) result.annotation = metadata({ version: key === 2 ? 99 : "invalid", payload: "<script>bad()</script>" }, key === 2 ? "unsupported_version" : "invalid");
      if (key === 2) result.annotation.truncated = true;
      if (key === 8) result.evidence = metadata({ version: 99 }, "unsupported_version");
      if (key === 9) result.subject = metadata({ version: 99 }, "unsupported_version");
      if (key === 5) result.archived = true;
    } else {
      const next = query.has("before_id") || query.has("after_symbol");
      const records = kind === "symbol" ? [record(kind, next ? "SecondAlias" : "<svg onload=bad()>")] :
        (next ? [record(kind, 51)] : [1, 2, 3, 4, 5, 6, 7, 8, 9].map(key => record(kind, key)));
      result = { ...(kind === "correction" ? { corrections: records } : { records }),
        next_before: kind !== "symbol" && !next ? 50 : null, next_symbol: kind === "symbol" && !next ? "NextAlias" : null };
    }
    if (held?.predicate(path, options)) {
      const gate = held; held = null;
      return new Promise(resolve => { gate.release = () => resolve(result); gate.signal(); });
    }
    return result;
  };
  const ui = window.SMSResearchUI.create(root, { api, getSlug: () => slug });
  const choose = async kind => { subject = kind; node("scope").value = kind; await node("scope").onchange(); };
  const inspect = key => root.querySelector(`[data-research-key="${key}"]`).onclick();
  const newDraft = () => {
    node("new").onclick();
    if (subject === "correction") set("reason", "The authored fixture describes this declared range.");
    if (subject === "note") set("text", "A tentative note for the authored fixture.");
    if (subject === "symbol") set("symbol", "ExistingAlias");
  };
  const lastPost = () => calls.filter(c => c.options?.method === "POST").at(-1);
  try {
    await ui.render(overview());
    assert(!node("more").hidden && node("apply").disabled, "listing exposes a bounded next page without granting application");
    await node("more").onclick();
    assert(calls.at(-1).path.includes("before_id=50") && node("more").hidden && node("list").children.length === 1, "correction pages replace the preceding page");
    await choose("note");
    for (const [key, state] of [[2, "unsupported"], [3, "stale"], [4, "unavailable"], [5, "archived"], [6, "untrusted review"], [7, "invalid"], [8, "unsupported"], [9, "unsupported"]]) {
      await inspect(key);
      assert(node("detail").textContent.includes(state), `inspection exposes ${state}`);
      if (key === 6) assert(node("detail").textContent.includes("review authority untrusted") && node("detail").textContent.includes("claimed-operator"), "claimed JSON receipts do not confer review authority");
      assert(!root.querySelector("img,svg,script"), "all metadata and references remain inert text");
      if ([2, 3, 4, 5, 7, 8, 9].includes(key)) assert(node("accept").hidden && node("reject").hidden, "unqualified or inactive subjects cannot be reviewed");
      if ([2, 5, 7, 8, 9].includes(key)) assert(node("edit").hidden, "opaque and archived subjects are read-only");
      if (key === 2) assert(node("detail").textContent.includes("Metadata clipped"), "clipped raw evidence is marked");
      if (key === 5) assert(node("clear").hidden && !node("copy").hidden, "an archive permits only a fresh proposal");
    }
    await inspect(5); node("copy").onclick();
    await node("preview").onclick();
    const copied = lastPost().options.body;
    assert(!copied.id && copied.text === "Original archived prose." && !copied.function, "forward recovery is a new note without an invented attachment");
    assert(copied.evidence.origin === null && copied.evidence.revision === null && copied.evidence.context === null && copied.evidence.subject_sha256 === null &&
      copied.evidence.review.state === "pending" && copied.evidence.review.actor === null, "copying never transfers origin, bindings or approval");
    const beforeDiscard = calls.length;
    node("discard").onclick();
    assert(node("apply").disabled && calls.length === beforeDiscard && !node("detail").textContent, "discarding a proposal changes no stored research");
    await choose("note"); await inspect(2); await node("clear").onclick();
    assert(lastPost().options.body.action === "clear" && !lastPost().options.body.apply, "opaque metadata detachment is previewed explicitly");
    await node("apply").onclick();
    assert(lastPost().options.body.expected_plan && node("apply").disabled, "detachment consumes its exact preview");
    newDraft();
    const badJSON = '{"encoding":"bytes","encoding":"ascii"}';
    field("kind").value = "data"; field("kind").onchange(); set("spec", badJSON);
    const beforeInvalid = calls.length;
    await node("preview").onclick();
    assert(calls.length === beforeInvalid && node("apply").disabled, "duplicate JSON fields cannot be silently accepted");
    set("spec", '{"encoding":"bytes"}');
    const gate = defer((_path, options) => options?.body?.apply === false);
    const oldPreview = node("preview").onclick(); await gate.started;
    set("text", "A newer edited note.");
    await node("preview").onclick();
    gate.release(); await oldPreview;
    assert(!node("apply").disabled, "a late prior response cannot erase a newer valid preview");
    await node("apply").onclick();
    assert(lastPost().options.body.text === "A newer edited note.", "only the latest exact draft is published");
    newDraft(); await node("preview").onclick();
    set("text", "An edit after preview invalidates it.");
    const beforeApply = calls.length; await node("apply").onclick();
    assert(node("apply").disabled && calls.length === beforeApply, "editing invalidates the old lease immediately");
    await node("preview").onclick(); failApply = true; await node("apply").onclick();
    assert(node("apply").disabled && node("status").textContent.includes("work changed"), "stale server guards require a fresh preview");
    failApply = false;
    await choose("symbol");
    assert(!root.querySelector("svg"), "symbol names are inert text");
    await node("more").onclick();
    assert(calls.at(-1).path.includes("after_symbol=NextAlias") && node("list").textContent.includes("SecondAlias"), "symbol paging uses exact names rather than note IDs");
    await choose("note");
    const inspection = defer(path => path.includes("id=1"));
    const oldInspection = inspect(1); await inspection.started;
    slug = "gg-b"; await ui.render(overview()); inspection.release(); await oldInspection;
    assert(!node("detail").textContent && node("apply").disabled, "late inspection cannot populate another project");
    newDraft();
    const pending = defer((_path, options) => options?.body?.apply === false);
    const old = node("preview").onclick(); await pending.started;
    slug = "sms-c"; await ui.render(overview()); pending.release(); await old;
    assert(node("apply").disabled && field("text").value !== "A tentative note for the authored fixture.", "project switches clear draft fields and late previews");
    newDraft(); await node("preview").onclick();
    await ui.render({ ...overview(), sms_profile: { mapper: "codemasters" } });
    assert(node("apply").disabled, "a declared mapping change invalidates previews");
    newDraft(); await node("preview").onclick();
    const publishing = defer((_path, options) => options?.body?.apply === true);
    const writing = node("apply").onclick(); await publishing.started;
    assert(node("scope").disabled && field("text").matches(":disabled"), "publication locks the draft and subject controls");
    slug = "gg-d"; await ui.render(overview()); publishing.release(); await writing;
    assert(!node("detail").textContent && node("apply").disabled, "a late publication reply cannot attach to another project");
    for (const overview of [{ slug, platform: "gb", sms_progress: {} }, { ...{ slug, platform: "sms", sms_progress: {} }, room: { role: "guest" } }, { slug, platform: "sms", sms_progress: {}, kind: "fork" }]) {
      await ui.render(overview); assert(root.hidden && node("apply").disabled, "other platforms, guests and forks keep their existing workflows");
    }
    document.getElementById("report").textContent = "PASS: bounded pages, original evidence, fresh forward proposals, stale guards, edit races, project/context switches and publication locks";
  } catch (error) { document.getElementById("report").textContent = "FAIL: " + error.stack; }
})();
