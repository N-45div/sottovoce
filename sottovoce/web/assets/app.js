"use strict";

const $ = (id) => document.getElementById(id);
const AUDIENCES = { it: "Italiano · per bambini", en: "English · for children" };
const STATUS = {
  verified: "verified",
  approved: "approved by a person",
  needs_review: "needs review · not aired",
  skipped: "black screen · nothing to describe",
  pending: "writing…",
};
let current = null;
let source = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "style") node.style.cssText = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value);
  }
  for (const child of children.flat()) if (child !== null && child !== undefined) node.append(child);
  return node;
}

// Extended description holds the picture while a long line is spoken, so with
// description on, every time after a hold lands later. Same rule as export.py.
function timeMap() {
  const extended = current?.status === "done" && $("ad-toggle").checked; // every lesson audience holds the picture
  const cues = current?.script?.cues || [];
  const holds = extended
    ? cues
        .filter((c) => (c.status === "verified" || c.status === "approved") && c.audio && c.seconds > c.end - c.start)
        .map((c) => [c.end, c.seconds - (c.end - c.start) + 0.3])
    : [];
  const shift = (t) => t + holds.filter(([at]) => at <= t).reduce((sum, [, extra]) => sum + extra, 0);
  const total = (current?.script?.duration || $("video").duration || 0) + holds.reduce((sum, [, extra]) => sum + extra, 0);
  return { shift, total };
}

const clock = (s) => {
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
};

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function loadLibrary() {
  const jobs = await api("/api/jobs");
  $("library").replaceChildren(
    ...jobs.map((job) =>
      el("li", {},
        el("button", { type: "button", "aria-current": String(current?.id === job.id), onclick: () => openJob(job.id) },
          el("span", { class: "lib-title" }, job.title),
          el("span", { class: "lib-meta" },
            el("span", { class: "badge" }, AUDIENCES[job.audience]?.split(":")[0] || job.audience),
            el("span", { class: `badge ${job.status}` }, job.status)),
        ),
      ),
    ),
  );
  if (!jobs.length) $("library").append(el("li", { class: "small" }, "No videos yet."));
  const sample = jobs.find((j) => j.status === "done" && j.audience === "it") || jobs.find((j) => j.status === "done");
  $("open-sample").hidden = !sample || Boolean(current);
  if (sample) $("open-sample").onclick = () => openJob(sample.id);
  return jobs;
}

async function openJob(id) {
  if (source) source.close();
  const job = await api(`/api/jobs/${id}`);
  current = job;
  history.replaceState(null, "", `#${id}`);
  $("empty").hidden = true;
  $("job").hidden = false;
  $("job-audience").textContent = AUDIENCES[job.audience] || job.audience;
  $("title").textContent = job.title;
  renderStatus(job);
  renderStats(job);
  renderCues(job.script ? job.script.cues : [], false);
  setVideo();
  await loadLibrary();
  if (job.status === "queued" || job.status === "running") follow(id);
}

function renderStatus(job) {
  const badge = $("job-status");
  badge.className = `badge ${job.status}`;
  badge.textContent = job.status === "failed" ? `failed: ${job.error}` : job.status;
  for (const [link, name] of [["dl-video", "described"], ["dl-narration", "narration"], ["dl-vtt", "vtt"]]) {
    $(link).href = `/files/${job.id}/${name}`;
    $(link).hidden = job.status !== "done";
  }
}

function renderStats(job) {
  const cues = job.script ? job.script.cues : [];
  const count = (status) => cues.filter((c) => c.status === status).length;
  const stats = [
    ["Lines", cues.filter((c) => c.status !== "skipped").length],
    ["Verified by the checker", count("verified")],
    ["Approved by a person", count("approved")],
    ["Need review", count("needs_review")],
  ];
  if (job.cost_per_minute !== null && job.cost_per_minute !== undefined) {
    stats.push(["Model cost per minute", el("span", {}, `$${job.cost_per_minute.toFixed(4)}`, el("small", {}, "AMD Token Factory list prices"))]);
  }
  if (job.script?.timings?.describe) {
    const total = Object.values(job.script.timings).reduce((a, b) => a + b, 0);
    stats.push(["Processing time", el("span", {}, `${Math.round(total)} s`, el("small", {}, `for ${Math.round(job.script.duration)} s of video`))]);
  }
  if (job.models?.describer) {
    stats.push(["Written by", el("span", { class: "model" }, job.models.describer, el("small", {}, `checked by ${job.models.verifier}`))]);
  }
  $("stats").replaceChildren(...stats.map(([label, value]) => el("div", {}, el("dt", {}, label), el("dd", {}, value))));
}

function renderCues(cues, animate) {
  const shown = cues.map((cue, i) => [cue, i]);
  $("cues").replaceChildren(...shown.map(([cue, i]) => cueCard(cue, i, animate)));
  if (!cues.length && current.status === "done") {
    $("cues").append(el("li", { class: "card small" }, "The dialogue leaves no pause long enough for a description in this video."));
  }
  renderTimeline(cues);
}

function renderTimeline(cues) {
  const { shift, total } = timeMap();
  const blocks = total
    ? cues.map((cue, i) => {
        const start = shift(cue.start);
        const length = Math.max(cue.end - cue.start, cue.seconds || 0);
        return el("button", {
          type: "button",
          class: `block ${cue.status}`,
          title: `${clock(cue.start)} ${cue.line || STATUS[cue.status] || ""}`,
          "aria-label": `Line ${i + 1} at ${clock(cue.start)}`,
          style: `left:${(start / total) * 100}%;width:${Math.max(0.6, (length / total) * 100)}%`,
          onclick: (event) => { event.stopPropagation(); seek(cue.start); },
        });
      })
    : [];
  $("timeline").replaceChildren(...blocks, $("playhead"));
}

function cueCard(cue, index, animate) {
  const done = current.status === "done";
  const text = el("textarea", { rows: 2, "aria-label": `Line at ${clock(cue.start)}` });
  text.value = cue.line;
  text.disabled = !done || cue.status === "skipped";
  const check = el("button", { type: "button", class: "btn btn-ghost btn-small", disabled: !done || cue.status === "skipped" }, "Check and re-voice");
  check.addEventListener("click", () => recheck(index, text.value, check));
  const approve = cue.status === "needs_review" && done && cue.line
    ? el("button", { type: "button", class: "btn btn-ghost btn-small", onclick: (e) => approveCue(index, e.currentTarget) }, "Approve as is")
    : null;
  const history = cue.history || [];
  const rounds = history.length > 1 || history.some((h) => h.problems.length)
    ? el("details", {},
        el("summary", {}, `${history.length} round${history.length > 1 ? "s" : ""} with the checker`),
        el("ol", {}, history.map((h) => el("li", {}, h.line || "(no line)", h.problems.map((p) => el("div", { class: "problem" }, `✗ ${p}`))))))
    : null;
  // A pointing or catch-up line sits in a sliver of time: the lesson holds there while it is spoken.
  const pause = cue.end - cue.start;
  const said = cue.seconds > pause ? "while the lesson waits" : `of ${pause.toFixed(1)} s`;
  return el("li", { class: `card cue${animate ? " new" : ""}`, "data-start": cue.start, "data-end": cue.end },
    el("div", { class: "cue-head" },
      el("button", { type: "button", class: "btn btn-ghost btn-small icon-btn", "aria-label": `Play from ${clock(cue.start)}`, onclick: () => seek(cue.start) }, "▶"),
      el("span", { class: "time" }, pause < 0.5 ? clock(cue.start) : `${clock(cue.start)} – ${clock(cue.end)}`),
      el("span", { class: `badge ${cue.status}` }, STATUS[cue.status] || cue.status),
      cue.seconds ? el("span", {}, `spoken in ${cue.seconds.toFixed(1)} s ${said}${cue.rate > 1 ? ` at ${cue.rate}×` : ""}`) : null,
    ),
    cue.status === "skipped" ? null : text,
    el("ul", { class: "chips" }, (cue.claims || []).map((c) => el("li", { class: `chip ${c.verdict}`, title: c.verdict.replace("_", " ") }, c.text))),
    rounds,
    cue.status === "skipped" ? null : el("div", { class: "cue-actions" }, check, approve),
  );
}

function follow(id) {
  source = new EventSource(`/api/jobs/${id}/events`);
  const cues = [];
  source.onmessage = async (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "cue") {
      cues[event.index] = event.cue;
      renderCues(cues.filter(Boolean).sort((a, b) => a.start - b.start), true);
      $("job-status").textContent = `running · ${cues.filter(Boolean).length} lines checked`;
    } else if (event.type === "status" && (event.status === "done" || event.status === "failed")) {
      source.close();
      await openJob(id);
    }
  };
}

function setVideo() {
  const video = $("video");
  const done = current.status === "done";
  const name = $("ad-toggle").checked && done ? "described" : "source";
  const at = video.currentTime;
  const playing = !video.paused;
  video.src = `/files/${current.id}/${name}?v=${Date.now()}`;
  video.addEventListener("loadedmetadata", () => {
    video.currentTime = at;
    if (playing) video.play();
    if (!current.script) renderTimeline([]);
  }, { once: true });
}

function seek(t) {
  const video = $("video");
  video.currentTime = Math.max(0, timeMap().shift(t) - 0.5);
  video.play();
}

async function recheck(index, line, button) {
  button.disabled = true;
  button.textContent = "Checking against the frames…";
  try {
    await api(`/api/jobs/${current.id}/cues/${index}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ line }),
    });
    await openJob(current.id);
  } catch (error) {
    button.textContent = `Failed: ${error.message}`;
    button.disabled = false;
  }
}

async function approveCue(index, button) {
  button.disabled = true;
  await api(`/api/jobs/${current.id}/cues/${index}/approve`, { method: "POST" });
  await openJob(current.id);
}

function upload(form) {
  const status = $("upload-status");
  const bar = $("progress-bar");
  const button = form.querySelector("button[type=submit]");
  const file = form.video.files[0];
  if (!file) { status.textContent = "Choose a video first."; return; }
  if (file.size > 30 * 1024 * 1024) { status.textContent = `This file is ${(file.size / 1048576).toFixed(0)} MB; the limit is 30 MB.`; return; }
  const request = new XMLHttpRequest();
  request.open("POST", "/api/jobs");
  request.upload.onprogress = (e) => { if (e.lengthComputable) bar.style.width = `${(e.loaded / e.total) * 100}%`; };
  request.onload = async () => {
    button.disabled = false;
    $("progress").hidden = true;
    let body = {};
    try { body = JSON.parse(request.responseText); } catch { /* not JSON */ }
    if (request.status >= 400) { status.textContent = body.detail || `Upload failed (${request.status}).`; return; }
    status.textContent = "";
    form.reset();
    $("drop-title").textContent = "Drop a lesson video here, or choose one";
    await openJob(body.id);
  };
  request.onerror = () => { button.disabled = false; $("progress").hidden = true; status.textContent = "The upload did not reach the server."; };
  button.disabled = true;
  $("progress").hidden = false;
  bar.style.width = "0";
  status.textContent = `Uploading ${file.name}…`;
  request.send(new FormData(form));
}

const drop = $("drop");
const input = drop.querySelector("input");
input.addEventListener("change", () => { $("drop-title").textContent = input.files[0]?.name || "Drop a lesson video here, or choose one"; });
["dragenter", "dragover"].forEach((type) => drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add("is-over"); }));
["dragleave", "drop"].forEach((type) => drop.addEventListener(type, () => drop.classList.remove("is-over")));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; input.dispatchEvent(new Event("change")); }
});
$("upload").addEventListener("submit", (e) => { e.preventDefault(); upload(e.target); });

$("ad-toggle").addEventListener("change", () => { setVideo(); if (current?.script) renderTimeline(current.script.cues); });
$("timeline").addEventListener("click", (e) => {
  const { total } = timeMap();
  if (!total) return;
  const box = e.currentTarget.getBoundingClientRect();
  const video = $("video");
  video.currentTime = ((e.clientX - box.left) / box.width) * total;
  video.play();
});
$("video").addEventListener("timeupdate", () => {
  const t = $("video").currentTime;
  const { shift, total } = timeMap();
  $("playhead").style.left = `${Math.min(100, (t / (total || 1)) * 100)}%`;
  for (const card of document.querySelectorAll(".cue")) {
    const start = shift(Number(card.dataset.start));
    const end = start + (Number(card.dataset.end) - Number(card.dataset.start));
    card.classList.toggle("playing", t >= start && t < end);
  }
});

const linked = location.hash.slice(1);
if (/^[0-9a-f]{12}$/.test(linked)) openJob(linked).catch(() => loadLibrary());
else loadLibrary().catch((error) => { $("upload-status").textContent = `Could not load the library: ${error.message}`; });
