"use strict";

function encode(value) {
  return JSON.stringify(value, (_key, item) => {
    if (item instanceof Uint8Array) {
      return {
        __codexBridgeType: "uint8array",
        base64: Buffer.from(item).toString("base64"),
      };
    }
    if (item instanceof ArrayBuffer) {
      return {
        __codexBridgeType: "arraybuffer",
        base64: Buffer.from(item).toString("base64"),
      };
    }
    return item;
  });
}

function decode(value) {
  const source = typeof value === "string" ? value : value.toString("utf8");
  return JSON.parse(source, (_key, item) => {
    if (!item || typeof item !== "object") {
      return item;
    }
    if (item.__codexBridgeType === "uint8array") {
      return Uint8Array.from(Buffer.from(item.base64, "base64"));
    }
    if (item.__codexBridgeType === "arraybuffer") {
      const bytes = Buffer.from(item.base64, "base64");
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    }
    return item;
  });
}

module.exports = { decode, encode };
