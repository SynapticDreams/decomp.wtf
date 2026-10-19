"use strict";
/* Authored examples describe geometry; their names and contents make no claim about an imported image. */
window.SMSResearchTemplates = {
  kinds: ["code", "data", "table", "operands", "noreturn", "record", "pointers", "split_pointers", "number", "mapping"],
  example(kind) {
    return structuredClone({
      code: { size: 1, spec: {} }, noreturn: { size: 1, spec: {} },
      data: { size: 16, spec: { encoding: "bytes" } }, table: { size: 8, spec: { count: 4 } },
      operands: { size: 1, spec: { bytes_after_call: 2 } },
      record: { size: 16, spec: { count: 4, stride: 4, overlap: "reject", fields: [
        { name: "flags", offset: 0, type: "bits", width: 1, endian: "little", bits: [{ name: "enabled", lsb: 0, width: 1 }] },
        { name: "handler", offset: 2, type: "ptr16le", bank: null, target: "code" }] } },
      pointers: { size: 16, spec: { count: 4, stride: 4, pointer_offset: 1, encoding: "u16le", target: "code",
        bank: { offset: 0, width: 1, meaning: "physical", source_sha256: null } } },
      split_pointers: { size: 12, spec: { count: 4, stride: 1, low_offset: 0, high_offset: 4, target: "code",
        bank: { offset: 8, width: 1, meaning: "register", source_sha256: null } } },
      number: { size: 2, spec: { value: 0, endian: "little" } },
      mapping: { size: 16, spec: { when: { banks: [0, 1, null] }, facts: { banks: [null, null, 2] } } }
    }[kind]);
  }
};
