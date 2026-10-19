"use strict";
/* Wait for authored async DOM fixtures through Chrome's debugger protocol. No external page is opened. */
const [endpoint, page] = process.argv.slice(2);
const socket = new WebSocket(endpoint);
let sequence = 0;
const pending = new Map();
const deadline = setTimeout(() => { console.error("Browser fixture did not finish within 15 seconds"); process.exit(1); }, 15000);
socket.addEventListener("message", event => {
  const message = JSON.parse(event.data);
  if (!pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
});
function command(method, params = {}, sessionId) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
}
socket.addEventListener("error", () => { console.error("Browser debugger connection failed"); process.exit(1); });
socket.addEventListener("open", async () => {
  try {
    const { targetId } = await command("Target.createTarget", { url: page });
    const { sessionId } = await command("Target.attachToTarget", { targetId, flatten: true });
    for (;;) {
      const reply = await command("Runtime.evaluate", { expression: 'document.getElementById("report")?.textContent', returnByValue: true }, sessionId);
      const value = reply.result?.value;
      if (typeof value === "string" && value !== "RUNNING") {
        console.log(value);
        clearTimeout(deadline);
        socket.close();
        process.exitCode = value.startsWith("PASS:") ? 0 : 1;
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 20));
    }
  } catch (error) { console.error(error.message); process.exit(1); }
});
