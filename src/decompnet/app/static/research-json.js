"use strict";
/* Bounded JSON for editable specifications. Reject duplicates rather than silently choosing a field. */
window.ResearchJSON = {
  parse(raw) {
    if (new TextEncoder().encode(raw).length > 65536) throw new Error("JSON is limited to 64 KiB.");
    let at = 0, nodes = 0;
    const fail = () => { throw new Error("Use JSON with unique keys and exact integers (no decimals)."); };
    const space = () => { while (/[ \t\r\n]/.test(raw[at] || "") && at < raw.length) at++; };
    const string = () => {
      const match = /"(?:\\.|[^"\\])*"/y;
      match.lastIndex = at;
      const token = match.exec(raw);
      if (!token) return fail();
      at = match.lastIndex;
      const value = JSON.parse(token[0]);
      if ([...value].length > 4096 || value.includes("\0")) throw new Error("JSON strings are limited to 4,096 characters.");
      return value;
    };
    const value = depth => {
      if (++nodes > 4096 || depth > 16) throw new Error("JSON exceeds its node or depth limit.");
      space();
      if (raw[at] === '"') return string();
      if (raw[at] === "{" || raw[at] === "[") {
        const object = raw[at++] === "{", end = object ? "}" : "]", result = object ? Object.create(null) : [];
        space();
        if (raw[at] === end) { at++; return result; }
        while (at < raw.length) {
          let key;
          if (object) {
            if (raw[at] !== '"') return fail();
            key = string();
            if ([...key].length > 128 || Object.hasOwn(result, key)) return fail();
            space();
            if (raw[at++] !== ":") return fail();
          }
          const item = value(depth + 1);
          if (object) result[key] = item; else result.push(item);
          space();
          if (raw[at] === end) { at++; return result; }
          if (raw[at++] !== ",") return fail();
          space();
        }
        return fail();
      }
      for (const [word, item] of [["null", null], ["true", true], ["false", false]]) {
        if (raw.startsWith(word, at)) { at += word.length; return item; }
      }
      const match = /^-?(?:0|[1-9][0-9]*)/.exec(raw.slice(at));
      if (!match || !Number.isSafeInteger(Number(match[0]))) return fail();
      at += match[0].length;
      return Number(match[0]);
    };
    const result = value(0);
    space();
    if (at !== raw.length) return fail();
    return result;
  }
};
