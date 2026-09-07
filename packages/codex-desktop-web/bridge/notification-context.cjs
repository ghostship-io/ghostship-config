"use strict";
const pending = [];
function validNavigationPath(value) {
  return typeof value === "string" && value.length < 2048 && value.startsWith("/") &&
    !value.startsWith("//") && !/[\\\x00-\x1f]/.test(value);
}
function trackNotificationPort(port) {
  port.on("message", ({ data }) => {
    const rpc = data?.[0] === "push" ? data[1] : null;
    const request = rpc?.[0] === "pipeline" && rpc?.[2]?.[0] === "show" ? rpc[3]?.[0] : null;
    if (!request?.conversationId || !validNavigationPath(request.navigationPath) ||
        typeof request.id !== "string" || typeof request.title !== "string") return;
    pending.push({ ...request, capturedAt: Date.now() });
    if (pending.length > 500) pending.shift();
  });
}
function takeNotificationMetadata(options) {
  const now = Date.now();
  for (let index = pending.length - 1; index >= 0; index--) {
    if (now - pending[index].capturedAt > 30000) pending.splice(index, 1);
  }
  const candidates = pending.filter((item) => item.title === options.title);
  if (!candidates.length) return;
  const plain = (value) => String(value || "").replace(/\s+/g, " ").trim();
  // Upstream strips Markdown before constructing Notification and its RPC read
  // loop resumes outside the delivery event's async context. Match its preserved
  // title/body; shared titles with different routes open the app rather than a wrong task.
  if (new Set(candidates.map((item) => item.navigationPath)).size > 1) {
    for (const item of candidates) item.navigationPath = "/";
  }
  const result = candidates.find((item) => plain(item.body) === plain(options.body)) || candidates[0];
  pending.splice(pending.indexOf(result), 1);
  return result;
}
module.exports = { trackNotificationPort, validNavigationPath, takeNotificationMetadata };
