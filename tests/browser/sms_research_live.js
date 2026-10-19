/* Synthetic declarations are exercised through the production API helper and the real authenticated app. */
(async () => {
  const assert = (value, why) => { if (!value) throw new Error(why); };
  const root = document.getElementById("smsResearch");
  const node = key => root.querySelector(`[data-research="${key}"]`);
  const field = key => root.querySelector(`[data-research-input="${key}"]`);
  const set = (key, value) => { field(key).value = value; field(key).dispatchEvent(new Event("input", { bubbles: true })); };
  const calls = [];
  const ui = window.SMSResearchUI.create(root, { api: async (path, options) => {
    const result = await api(path, options);
    calls.push({ path, options, result });
    return result;
  }, getSlug: () => researchFixture.overview.slug });
  const lastPost = () => calls.filter(c => c.options?.method === "POST").at(-1);
  const preview = async () => {
    await node("preview").onclick();
    assert(!node("apply").disabled, node("status").textContent);
    assert(lastPost().options.body.apply === false && !lastPost().result.applied, "preview is read-only");
    return structuredClone(lastPost().options.body);
  };
  const apply = async before => {
    await node("apply").onclick();
    const sent = lastPost();
    assert(sent.result.applied, node("status").textContent);
    const { apply: applied, expected_plan, ...body } = sent.options.body;
    const { apply: _preview, ...original } = before;
    assert(applied === true && expected_plan && JSON.stringify(body) === JSON.stringify(original), "application carries exactly the previewed draft");
    assert(node("apply").disabled, "a preview is consumed once");
    return sent.result.correction || sent.result.record;
  };
  const review = async (ok = true) => {
    assert(!node(ok ? "accept" : "reject").hidden, "current subject permits operator review");
    await node(ok ? "accept" : "reject").onclick();
    const intent = structuredClone(lastPost().options.body);
    assert(intent.action === "review" && intent.ok === ok, "review is a separate explicit boolean intent");
    return apply(intent);
  };
  try {
    await ui.render(researchFixture.overview);
    for (const kind of window.SMSResearchTemplates.kinds) {
      node("new").onclick();
      assert(field("reason").closest("fieldset").parentElement.getBoundingClientRect().width > root.getBoundingClientRect().width * 0.8,
        "a new proposal uses available width rather than an empty inspection column");
      field("kind").value = kind; field("kind").onchange();
      set("offset", "0x100"); set("at", "00:0100");
      set("reason", "The authored browser fixture declares this bounded layout for qualification.");
      if (kind === "record") {
        field("state").value = "static_derivation"; field("state").onchange();
        const before = calls.length;
        await node("preview").onclick();
        assert(calls.length === before && node("apply").disabled, "evidence states requiring links refuse an empty reference list");
        set("links", '[{"kind":"analysis","ref":"authored-layout-fixture","sha256":null}]');
        set("alternatives", "The same bytes could describe another record layout.");
      }
      const body = await preview();
      assert(body.annotation.kind === kind && body.annotation.target.offset === 256, "declaration kind and physical extent survive the editor");
      assert(body.evidence.revision === null && body.evidence.review.actor === null, "the caller never supplies review authority");
      const stored = await apply(body);
      assert(stored.application === "pending_review" && !stored.active, "new declarations do not become discovery facts");
      const approved = await review();
      assert(approved.application === (["code", "data", "table", "operands", "noreturn"].includes(kind) ? "legacy_hint" : "awaiting_consumer"), "review activates only qualified consumers");
      assert(node("detail").textContent.includes("review authority accepted"), "authenticated authority is visible separately from claimed JSON");
    }
    const rejected = await review(false);
    assert(rejected.application === "rejected" && !rejected.active, "rejection retains evidence without an active hint");
    await node("undo").onclick();
    assert(node("status").textContent.includes("Correction undone"), "undo retains the existing correction history workflow");
    node("scope").value = "note"; await node("scope").onchange();
    node("new").onclick();
    const text = "Authored browser note <img src=x> preserves its original function attachment.";
    set("text", text + "😀".repeat(4000 - text.length));
    set("function", researchFixture.symbol);
    const note = await apply(await preview());
    assert(note.annotation.raw === null && note.subject.value.entity.function.name === researchFixture.symbol, "evidence-only notes preserve attachment without an invented range");
    assert(!root.querySelector("img"), "note content is inert text");
    await review();
    await node("reload").onclick();
    await root.querySelector(`[data-research-key="${note.key}"]`).onclick();
    assert(node("detail").textContent.includes("review authority accepted"), "fresh inspection reloads authenticated saved research");
    node("edit").onclick();
    assert(field("text").readOnly && field("function").disabled, "metadata edits cannot rewrite the original prose or attachment");
    set("alternatives", "The original tentative interpretation needs further evidence.");
    const edit = await preview();
    assert(edit.id === note.key && edit.text === "" && !edit.function && edit.evidence.review.state === "pending", "metadata edits target the exact note with fresh pending evidence");
    const replaced = await apply(edit);
    assert(replaced.application === "pending_review" && replaced.text === note.text, "replacement archives metadata and preserves note prose");
    await node("clear").onclick();
    const cleared = await apply(structuredClone(lastPost().options.body));
    assert(cleared.application === "legacy_unknown" && cleared.text === note.text, "detachment preserves prose and the existing subject");
    node("scope").value = "symbol"; await node("scope").onchange();
    await root.querySelector(`[data-research-key="${researchFixture.symbol}"]`).onclick();
    node("edit").onclick();
    field("kind").value = "record"; field("kind").onchange();
    field("space").value = "wram"; set("offset", "0");
    const symbol = await apply(await preview());
    assert(symbol.subject.value.source.space === "wram" && symbol.subject.value.source.contents === "unobserved", "RAM declarations carry no fabricated ROM bytes or captured contents");
    const accepted = await review();
    assert(accepted.application === "reviewed_research" && accepted.discovery === false, "reviewed symbol meanings remain research");
    document.getElementById("report").textContent = "PASS: all declaration kinds, exact preview/apply, authenticated review, notes, symbols, RAM, archive preservation and undo over real HTTP";
  } catch (error) { document.getElementById("report").textContent = "FAIL: " + error.stack; }
})();
