"use strict";
/* Research values, including external references and unsupported metadata, are always inert text. */
window.SMSResearchView = {
  el(tag, text, parent) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (parent) parent.append(node);
    return node;
  },
  button(text, parent, key, action) {
    const node = this.el("button", text, parent);
    node.type = "button"; node.className = "ghost small-btn";
    node.dataset.research = key; node.onclick = action;
    return node;
  },
  label(value) { return String(value ?? "unknown").replaceAll("_", " "); },
  summary(record) {
    return `${this.label(record.application)} · binding ${this.label(record.binding)} · ` +
      `review authority ${this.label(record.review)} · ${this.label(record.state)} / ${this.label(record.confidence)}`;
  },
  detail(panel, record) {
    panel.replaceChildren();
    this.el("h4", "Research inspection", panel);
    this.el("p", this.summary(record), panel);
    if (record.conflict) this.el("p", record.conflict, panel);
    if (record.archived) this.el("p", "Archived original subject: read-only and inactive. Copy a supported declaration into a new proposal to bind it afresh.", panel);
    if (record.reason) this.el("p", record.reason, panel);
    if (record.text !== undefined) this.el("pre", record.text + (record.text_truncated ? "\n[Text clipped by inspection limits]" : ""), panel);
    const identity = record.symbol || (record.function_id != null ? { function_id: record.function_id } : null);
    if (identity) this.el("pre", JSON.stringify(identity, null, 2), panel);
    this.el("p", record.active === true ? "Currently supplies a qualified legacy split hint." :
      "This record does not currently supply a discovery hint. Review does not establish runtime contents or semantic certainty.", panel);
    for (const [field, title] of [["annotation", "Declaration and geometry"], ["evidence", "Evidence, alternatives and claimed review"], ["subject", "Original subject and correspondence"]]) {
      const metadata = record[field];
      if (!metadata) continue;
      const box = this.el("details", undefined, panel);
      box.open = field !== "subject";
      this.el("summary", `${title} (${this.label(metadata.status)})`, box);
      const body = metadata.value == null ? String(metadata.raw ?? "No metadata") : JSON.stringify(metadata.value, null, 2);
      this.el("pre", body.slice(0, 80000) + (metadata.truncated || body.length > 80000 ? "\n[Metadata clipped by inspection limits]" : ""), box);
    }
  }
};
