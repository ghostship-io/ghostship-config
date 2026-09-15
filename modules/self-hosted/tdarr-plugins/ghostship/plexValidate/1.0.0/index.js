"use strict";

const details = () => ({
  name: "Validate Plex HEVC output",
  description: "Reject outputs that violate stream, size, or language policy.",
  style: { borderColor: "orange" },
  tags: "video,audio,subtitle",
  isStartPlugin: false,
  pType: "",
  requiresVersion: "2.11.01",
  sidebarPosition: -1,
  icon: "",
  inputs: [],
  outputs: [
    { number: 1, tooltip: "Valid output" },
    { number: 2, tooltip: "Validation failed" },
  ],
});

const plugin = async (args) => {
  const streams = args.inputFileObj?.ffProbeData?.streams || [];
  const originalStreams = args.originalLibraryFile?.ffProbeData?.streams || [];
  const errors = [];
  const video = streams.find((stream) => stream.codec_type === "video" && stream.codec_name !== "mjpeg");
  const originalVideo = originalStreams.find((stream) => stream.codec_type === "video" && stream.codec_name !== "mjpeg");
  const outputCodec = String(video?.codec_name || "").toLowerCase();
  const originalCodec = String(originalVideo?.codec_name || "").toLowerCase();
  if (!video) errors.push("primary video is missing");
  if (args.variables?.user?.plexVideoEncoded && outputCodec !== "hevc") errors.push("encoded video is not HEVC");
  if (!args.variables?.user?.plexVideoEncoded && outputCodec !== originalCodec) errors.push("copied video codec changed");
  if (video && originalVideo && (Number(video.width) !== Number(originalVideo.width) || Number(video.height) !== Number(originalVideo.height))) {
    errors.push("video dimensions changed");
  }
  const audio = streams.filter((stream) => stream.codec_type === "audio");
  if (audio.length === 0) errors.push("no audio remains");
  if (audio.some((stream) => Number(stream.channels || 0) > 6)) errors.push("audio exceeds 5.1 channels");
  const originalTags = args.variables?.user?.plexOriginalLanguageTags || [];
  const audioLanguages = audio.map((stream) => String(stream?.tags?.language || "").toLowerCase());
  if (!audioLanguages.some((value) => originalTags.includes(value))) errors.push("original-language audio is missing");
  if (audioLanguages.some((value) => value && !originalTags.includes(value))) errors.push("unrelated dubbed audio remains");

  const isForeign = !originalTags.includes("eng") && !originalTags.includes("en");
  const originalHadEnglishSubtitles = originalStreams.some((stream) => {
    const value = String(stream?.tags?.language || "").toLowerCase();
    return stream.codec_type === "subtitle" && ["eng", "en"].includes(value);
  });
  const hasEnglishSubtitles = streams.some((stream) => {
    const value = String(stream?.tags?.language || "").toLowerCase();
    return stream.codec_type === "subtitle" && ["eng", "en"].includes(value);
  });
  if (isForeign && (!originalHadEnglishSubtitles || !hasEnglishSubtitles)) errors.push("foreign-language title lacks retained English subtitles");

  const originalSize = Number(args.originalLibraryFile?.file_size || 0);
  const outputSize = Number(args.inputFileObj?.file_size || 0);
  const ratio = originalSize > 0 ? outputSize / originalSize : 1;
  const duration = Number(args.inputFileObj?.ffProbeData?.format?.duration || 0);
  const maximumSizeMb = duration > 0 ? (duration / 7200) * 20480 : 0;
  if (args.variables?.user?.plexVideoEncoded && ratio > 0.85) errors.push(`space saving is only ${((1 - ratio) * 100).toFixed(1)}%`);
  if (args.variables?.user?.plexVideoEncoded && ratio < 0.05) errors.push(`output is unexpectedly small (${(ratio * 100).toFixed(1)}%)`);
  if (args.variables?.user?.plexVideoEncoded && maximumSizeMb > 0 && outputSize > maximumSizeMb) {
    errors.push("output exceeds the duration-scaled 20 GiB ceiling");
  }

  if (errors.length > 0) args.jobLog(`Validation failed: ${errors.join("; ")}`);
  else args.jobLog(`Validation passed; output is ${(ratio * 100).toFixed(1)}% of the source size`);
  return {
    outputFileObj: args.inputFileObj,
    outputNumber: errors.length === 0 ? 1 : 2,
    variables: args.variables,
  };
};

module.exports = { details, plugin };
