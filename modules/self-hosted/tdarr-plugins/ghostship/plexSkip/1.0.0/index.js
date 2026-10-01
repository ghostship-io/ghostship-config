"use strict";

const details = () => ({
  name: "Record policy skip",
  description: "End the flow without changing the file. Tdarr records it as done and it never occupies the staging queue.",
  style: { borderColor: "grey" },
  tags: "file",
  isStartPlugin: false,
  pType: "",
  requiresVersion: "2.11.01",
  sidebarPosition: -1,
  icon: "faEyeSlash",
  inputs: [],
  outputs: [{ number: 1, tooltip: "Skipped" }],
});

// This node deliberately has no outgoing edge, so the flow ends here. Tdarr
// records the unchanged result as a finished transcode and keeps the file
// record, which stops it from being re-queued on every scan. Do not set
// removeFromTdarr: that deletes the record while the file stays on disk, so
// the next scan re-adds it and the file cycles forever. Do not use
// requireReview either: a full staging queue blocks all transcoding.
const plugin = async (args) => {
  args.jobLog("Policy skip: file left untouched and recorded as done");
  return {
    outputFileObj: args.inputFileObj,
    outputNumber: 1,
    variables: args.variables,
  };
};

module.exports = { details, plugin };
