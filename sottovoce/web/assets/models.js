// The models a lesson records, as people know them, and where each one runs.
// Gemma 4 wrote the library lessons on AMD Token Factory until AMD retired it
// there on Oct 16; it now writes on Google Cloud's Vertex AI.
const MODEL_NAMES = {
  "Gemma-4-31B-IT": ["Gemma 4", "AMD Instinct GPUs"],
  "google/gemma-4-26b-a4b-it-maas": ["Gemma 4", "Google Cloud"],
  "DeepSeek-V4.1-Flash": ["DeepSeek-V4.1", "AMD Instinct GPUs"],
  "DeepSeek-V4-Flash-Vision-Exp": ["DeepSeek-V4 Vision", "AMD Instinct GPUs"],
  "Qwen3.8-27B": ["Qwen3.8", "AMD Instinct GPUs"],
  "Qwen3.8-Flash-Next": ["Qwen3.8 Flash", "AMD Instinct GPUs"],
  teacher: ["the teacher", ""],
};
const named = (model) => (MODEL_NAMES[model] || [model])[0];
const runsOn = (model) => (MODEL_NAMES[model] || [])[1] || "";
const namedOn = (model) => (runsOn(model) ? `${named(model)} on ${runsOn(model)}` : named(model));
