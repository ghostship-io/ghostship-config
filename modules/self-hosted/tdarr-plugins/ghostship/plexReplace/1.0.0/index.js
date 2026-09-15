"use strict";

const fs = require("fs");

const details = () => ({
  name: "Replace original without a gap",
  description: "Copy the validated output beside the original, then atomically rename over it.",
  style: { borderColor: "green" },
  tags: "file",
  isStartPlugin: false,
  pType: "",
  requiresVersion: "2.11.01",
  sidebarPosition: -1,
  icon: "",
  inputs: [],
  outputs: [{ number: 1, tooltip: "Original replaced" }],
});

const plugin = async (args) => {
  const source = String(args.inputFileObj?._id || "");
  const original = String(args.originalLibraryFile?._id || "");
  if (!original.startsWith("/media/")) {
    throw new Error("plexReplace only replaces files under /media");
  }
  if (!source) throw new Error("plexReplace is missing the working file");
  if (source === original && Number(args.inputFileObj?.file_size || 0) === Number(args.originalLibraryFile?.file_size || 0)) {
    args.jobLog("File has not changed; leaving the original in place");
    return { outputFileObj: args.inputFileObj, outputNumber: 1, variables: args.variables };
  }

  const tmp = `${original}.tdarr-new`;
  try {
    await fs.promises.unlink(tmp);
    args.jobLog(`Removed leftover ${tmp}`);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }

  args.jobLog(`Copying ${source} beside the original as ${tmp}`);
  await fs.promises.copyFile(source, tmp);
  const handle = await fs.promises.open(tmp, "r+");
  await handle.sync();
  await handle.close();

  args.jobLog(`Atomically replacing ${original}`);
  await fs.promises.rename(tmp, original);
  return {
    outputFileObj: { _id: original },
    outputNumber: 1,
    variables: args.variables,
  };
};

module.exports = { details, plugin };
