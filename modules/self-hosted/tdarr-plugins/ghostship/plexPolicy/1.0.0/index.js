"use strict";

const fs = require("fs");

const details = () => ({
  name: "Plex HEVC policy",
  description: "Apply the guarded Ghostship HEVC, audio, and subtitle policy.",
  style: { borderColor: "#6efefc" },
  tags: "video,audio,subtitle",
  isStartPlugin: false,
  pType: "",
  requiresVersion: "2.11.01",
  sidebarPosition: -1,
  icon: "",
  inputs: [
    {
      label: "Pilot original language tags",
      name: "pilotOriginalLanguageTags",
      type: "string",
      defaultValue: "eng,en",
      inputUI: { type: "text" },
      tooltip: "Used only for staged files below /media. Production requires arr metadata.",
    },
  ],
  outputs: [
    { number: 1, tooltip: "Encode or remux" },
    { number: 2, tooltip: "Manual review required" },
    { number: 3, tooltip: "Already compliant" },
  ],
});

const language = (stream) => String(stream?.tags?.language || "").trim().toLowerCase();
const title = (stream) => String(stream?.tags?.title || "").trim().toLowerCase();
const isCommentary = (stream) => /commentary|director|producer|screenwriter|cast and crew/.test(title(stream));

const plugin = async (args) => {
  const lib = require("../../../../../methods/lib")();
  args.inputs = lib.loadDefaultValues(args.inputs, details);
  const command = args.variables?.ffmpegCommand;
  if (!command?.init) throw new Error("Plex HEVC policy requires Begin Command first");

  const filePath = String(args.inputFileObj?._id || "");
  let tags = [];
  let languageName = "";
  if (filePath.startsWith("/media/")) {
    tags = String(args.inputs.pilotOriginalLanguageTags)
      .split(",").map((value) => value.trim().toLowerCase()).filter(Boolean);
    languageName = "pilot override";
  } else {
    let policy;
    try {
      policy = JSON.parse(fs.readFileSync("/policy/original-languages.json", "utf8"));
    } catch (error) {
      args.jobLog(`Original-language policy unavailable: ${error.message}`);
      return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
    }
    const root = Object.keys(policy.roots || {})
      .filter((candidate) => filePath === candidate || filePath.startsWith(`${candidate}/`))
      .sort((left, right) => right.length - left.length)[0];
    const entry = root ? policy.roots[root] : null;
    tags = Array.isArray(entry?.tags) ? entry.tags.map((value) => String(value).toLowerCase()) : [];
    languageName = String(entry?.name || "");
  }

  if (tags.length === 0) {
    args.jobLog(`Manual review: original language is unknown for ${filePath}`);
    return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
  }

  const video = command.streams.find((stream) => stream.codec_type === "video" && stream.codec_name !== "mjpeg");
  if (!video) {
    args.jobLog("Manual review: no primary video stream");
    return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
  }
  if (Number(video.width) > 1920 || Number(video.height) > 1080) {
    args.jobLog("Manual review: pilot does not change video above 1080p");
    return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
  }
  const transfer = String(video.color_transfer || "").toLowerCase();
  if (["smpte2084", "arib-std-b67"].includes(transfer)) {
    args.jobLog("Manual review: pilot does not change HDR video");
    return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
  }
  const fieldOrder = String(video.field_order || "unknown").toLowerCase();
  if (!["progressive", "unknown", ""].includes(fieldOrder)) {
    args.jobLog(`Manual review: interlaced field order ${fieldOrder}`);
    return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
  }

  const audio = command.streams.filter((stream) => stream.codec_type === "audio");
  if (audio.length === 0 || audio.some((stream) => language(stream) === "")) {
    args.jobLog("Manual review: audio language tags are missing");
    return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
  }
  if (audio.some(isCommentary)) {
    args.jobLog("Manual review: commentary or a meaningful alternate audio track is present");
    return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
  }
  const originals = audio.filter((stream) => tags.includes(language(stream)));
  if (originals.length === 0) {
    args.jobLog(`Manual review: no ${languageName} audio track matches ${tags.join(",")}`);
    return { outputFileObj: args.inputFileObj, outputNumber: 2, variables: args.variables };
  }

  let changed = false;
  for (const stream of audio) {
    if (!tags.includes(language(stream))) {
      stream.removed = true;
      changed = true;
      args.jobLog(`Removing unrelated dubbed audio stream ${stream.index} (${language(stream)})`);
      continue;
    }
    const channels = Number(stream.channels || 0);
    const compatible = ["aac", "ac3", "eac3"].includes(String(stream.codec_name).toLowerCase());
    if (channels > 6 || !compatible) {
      const outputChannels = Math.min(Math.max(channels, 1), 6);
      const bitrate = outputChannels >= 6 ? "640k" : outputChannels >= 4 ? "448k" : outputChannels === 2 ? "256k" : "128k";
      stream.outputArgs.push(
        "-c:{outputIndex}", "ac3",
        "-ac:{outputIndex}", String(outputChannels),
        "-b:{outputIndex}", bitrate,
      );
      changed = true;
    }
  }

  for (const stream of command.streams.filter((candidate) => candidate.codec_type === "subtitle")) {
    const streamLanguage = language(stream);
    if (streamLanguage && streamLanguage !== "eng" && streamLanguage !== "en" && !tags.includes(streamLanguage)) {
      stream.removed = true;
      changed = true;
    }
  }

  const duration = Number(args.inputFileObj?.ffProbeData?.format?.duration || 0);
  const fileSizeMb = Number(args.inputFileObj?.file_size || 0);
  const sizeTargetMb = duration > 0 ? (duration / 7200) * 10240 : 0;
  const codec = String(video.codec_name || "").toLowerCase();
  const shouldEncodeVideo = codec !== "hevc" && codec !== "h265" && (sizeTargetMb === 0 || fileSizeMb > sizeTargetMb);
  if (shouldEncodeVideo) {
    const pixelFormat = String(video.pix_fmt || "").includes("10") ? "yuv420p10le" : "yuv420p";
    video.outputArgs.push(
      "-c:{outputIndex}", "libx265",
      "-preset", "slow",
      "-crf", "20",
      "-pix_fmt", pixelFormat,
      "-x265-params", "pools=8:frame-threads=4",
    );
    args.variables.user = { ...(args.variables.user || {}), plexVideoEncoded: true };
    changed = true;
  }

  command.container = "mkv";
  command.shouldProcess = changed;
  args.variables.user = {
    ...(args.variables.user || {}),
    plexOriginalLanguageTags: tags,
    plexOriginalLanguageName: languageName,
  };
  args.jobLog(`Original language: ${languageName} (${tags.join(",")})`);
  return {
    outputFileObj: args.inputFileObj,
    outputNumber: changed ? 1 : 3,
    variables: args.variables,
  };
};

module.exports = { details, plugin };
