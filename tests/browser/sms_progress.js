/* Authored evidence dimensions; no game assets or source are needed to inspect these states. */
(() => {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const panel = document.getElementById("panel");
  const metrics = { input: { status: "verified" }, discovered_code_bytes: 100, documented_assembly: { bytes: 20 },
    c_reference: { bytes: 10 }, classified_data: { bytes: 30, code_overlap_bytes: 5 },
    semantic_review: { pending: 2, unknown: 8 } };
  const verification = { passed: false, receipt_valid: true, image: { checked: true, equal: true },
    documented: { expected: 2, inserted: 1, omitted: 1, inserted_bytes: 20, required: true,
      omissions: [{ name: "<img src=x>", reason: "authored omission" }] },
    errors: ["required_documented_source_omitted"] };
  try {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    panel.append(svg);
    window.SMSProgressUI.timeline(svg, { baseline_bytes: 4, bytes: 15, points: [[20, 12], [30, 15]] }, 40);
    assert(svg.querySelectorAll("path").length === 2 && svg.querySelector("path.line").getAttribute("d").endsWith("H200"),
      "the chart consumes bounded union-byte totals rather than summing overlapping entries");
    window.SMSProgressUI.render(panel, { sms_progress: metrics, export: { current: false, verification } });
    assert(panel.textContent.includes("Overall verification failed") && panel.textContent.includes("equality passed at that build"),
      "strict failure does not rewrite measured image equality");
    assert(panel.textContent.includes("1 of 2 routines") && panel.textContent.includes("Strict insertion required"),
      "insertions and omitted source remain separate");
    assert(panel.textContent.includes("historical / current context differs") && panel.textContent.includes("Typed data remains unqualified"),
      "historical checks and unqualified data stay explicit");
    assert(panel.textContent.includes("2 pending, 8 unknown") && panel.textContent.includes("not linked replacements"),
      "unsampled status is not semantic approval or linked C");
    assert(!panel.querySelector("img") && panel.textContent.includes("<img src=x>"), "omissions render as text");
    window.SMSProgressUI.render(panel, { sms_progress: { ...metrics, input: { status: "missing" } }, export: { identical: true } });
    assert(panel.textContent.includes("input: missing") && panel.textContent.includes("older export record is unqualified"),
      "legacy success cannot imply current input verification");
    window.SMSProgressUI.result(panel, { verification: { passed: false, image: { checked: true, equal: true } }, documented: 1,
      left_out: [["<img src=x>", "authored refusal"]] });
    assert(panel.textContent.includes("verification failed") && panel.textContent.includes("equality: equal") &&
      panel.textContent.includes("1 assembly routines inserted"), "result reports actual insertion even on strict failure");
    assert(!panel.querySelector("img"), "result text is escaped");
    window.SMSProgressUI.result(panel, { verification: { passed: true, image: { checked: true, equal: true } },
      left_out: Array.from({ length: 130 }, (_, i) => [`Entry${i}`, "authored"]) });
    assert(panel.querySelectorAll("p").length === 102 && panel.textContent.includes("Showing 100 omissions"),
      "large results use a bounded visible omission list");
    window.SMSProgressUI.result(panel, { verification: { passed: false, receipt_valid: false,
      image: { checked: false, equal: null }, build: { image: { equal: true } } } });
    assert(panel.textContent.includes("equality: not verified"), "untrusted report claims cannot become measured equality");
    window.SMSProgressUI.render(panel, {});
    assert(!panel.childNodes.length, "switching to another platform clears old SMS evidence");
    document.getElementById("report").textContent = "PASS: separate dimensions, historical checks, policy failures and escaped bounded results";
  } catch (error) { document.getElementById("report").textContent = "FAIL: " + error.stack; }
})();
