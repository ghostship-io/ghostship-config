"use strict";
const { AsyncLocalStorage } = require("node:async_hooks");
const context = new AsyncLocalStorage();
function validNavigationPath(value) {
  return typeof value === "string" && value.length < 2048 && value.startsWith("/") &&
    !value.startsWith("//") && !/[\\\x00-\x1f]/.test(value);
}
function trackNotificationPort(port) {
  const emit = port.emit;
  port.emit = function (event, message, ...args) {
    const rpc = event === "message" && message?.data?.[0] === "push" ? message.data[1] : null;
    const request = rpc?.[0] === "pipeline" && rpc?.[2]?.[0] === "show" ? rpc[3]?.[0] : null;
    // Carry the upstream notification's route through asynchronous RPC handling;
    // Electron's Notification options otherwise discard this desktop metadata.
    const target = request?.conversationId && validNavigationPath(request.navigationPath)
      ? request.navigationPath : undefined;
    return context.run(target, () => emit.call(this, event, message, ...args));
  };
}
module.exports = { trackNotificationPort, validNavigationPath, currentNotificationPath: () => context.getStore() };
