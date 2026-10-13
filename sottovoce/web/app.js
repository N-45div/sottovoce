"use strict";

const $ = (id) => document.getElementById(id);
const AUDIENCES = { it: "Italian", en: "English", extended: "Italian, extended" };
const STATUS = { verified: "verified", approved: "approved by a person", needs_review: "needs review", pending: "writing…" };
let current = null;
let source = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null) node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
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
  const list = $("library");
  list.replaceChildren(
    ...jobs.map((job) =>
      el("li", {},
        el("button", { type: "button", "aria-current": String(current?.id === job.id), onclick: () => openJob(job.id) },
          el("span", {}, job.title),
          el("small", {}, `${AUDIENCES[job.audience] || job.audience} · ${job.status}`),
        ),
      ),
    ),
  );
  if (!jobs.length) list.append(el("li", { class: "hint" }, "No videos yet."));
}

async function openJob(id) {
  if (source) source.close();
  const job = await api(`/api/jobs/${id}`);
  current = job;
  history.replaceState(null, "", `#${id}`);
  $("empty").hidden = true;
  $("job").hidden = false;
  $("title").textContent = `${job.title} · ${AUDIENCES[job.audience] || job.audience}`;
  renderStatus(job);
  renderStats(job);
  renderCues(job.script ? job.script.cues : []);
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
    ["Lines", cues.length],
    ["Verified by the checker", count("verified")],
    ["Approved by a person", count("approved")],
    ["Need review", count("needs_review")],
  ];
  if (job.cost_per_minute !== null && job.cost_per_minute !== undefined) {
    stats.push(["AMD cost per minute of video", el("span", {}, `$${job.cost_per_minute.toFixed(4)}`, el("br"), el("small", {}, "a human describer: $15–75"))]);
  }
  if (job.script?.timings?.describe) {
    const total = Object.values(job.script.timings).reduce((a, b) => a + b, 0);
    stats.push(["Processing time", `${Math.round(total)} s`]);
  }
  $("stats").replaceChildren(...stats.map(([label, value]) => el("div", {}, el("dt", {}, label), el("dd", {}, value))));
}

function renderCues(cues) {
  $("cues").replaceChildren(...cues.map((cue, i) => cueCard(cue, i)));
  if (!cues.length && current.status === "done") {
    $("cues").append(el("li", { class: "hint" }, "The dialogue leaves no pause long enough for a description in this video."));
  }
}

function cueCard(cue, index) {
  const text = el("textarea", { rows: 2, "aria-label": `Line at ${clock(cue.start)}` });
  text.value = cue.line;
  const done = current.status === "done";
  text.disabled = !done;
  const check = el("button", { type: "button", class: "quiet", disabled: done ? null : "" }, "Check and re-voice");
  check.addEventListener("click", () => recheck(index, text.value, check));
  const approve = cue.status === "needs_review" && done
    ? el("button", { type: "button", class: "quiet", onclick: (e) => approveCue(index, e.target) }, "Approve as is")
    : null;
  const rewrites = (cue.history || []).length > 1 || (cue.history || []).some((h) => h.problems.length)
    ? el("details", {},
        el("summary", {}, `${cue.history.length} round${cue.history.length > 1 ? "s" : ""} with the checker`),
        el("ol", {}, cue.history.map((h) =>
          el("li", {}, h.line, h.problems.map((p) => el("div", { class: "problem" }, `✗ ${p}`))))))
    : null;
  return el("li", { class: "cue", "data-start": cue.start, "data-end": cue.end },
    el("div", { class: "cue-head" },
      el("button", { type: "button", class: "quiet", "aria-label": `Play from ${clock(cue.start)}`, onclick: () => seek(cue.start) }, "▶"),
      el("span", { class: "time" }, `${clock(cue.start)} – ${clock(cue.end)}`),
      el("span", { class: `badge ${cue.status}` }, STATUS[cue.status] || cue.status),
      cue.seconds ? el("span", {}, `spoken ${cue.seconds.toFixed(1)} s of ${(cue.end - cue.start).toFixed(1)} s${cue.rate > 1 ? ` at ${cue.rate}×` : ""}`) : null,
    ),
    text,
    el("ul", { class: "claims" }, (cue.claims || []).map((c) => el("li", { class: c.verdict, title: c.verdict.replace("_", " ") }, c.text))),
    rewrites,
    el("div", { class: "cue-actions" }, check, approve),
  );
}

function follow(id) {
  source = new EventSource(`/api/jobs/${id}/events`);
  const cues = [];
  source.onmessage = async (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "cue") {
      cues[event.index] = event.cue;
      renderCues(cues.filter(Boolean).sort((a, b) => a.start - b.start));
      $("job-status").textContent = `running · ${cues.filter(Boolean).length} lines written`;
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
  video.currentTime = at;
  if (playing) video.play();
}

function seek(t) {
  const video = $("video");
  video.currentTime = Math.max(0, t - 0.5);
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

$("ad-toggle").addEventListener("change", setVideo);
$("video").addEventListener("timeupdate", () => {
  const t = $("video").currentTime;
  for (const card of document.querySelectorAll(".cue")) {
    card.classList.toggle("playing", t >= Number(card.dataset.start) && t < Number(card.dataset.end));
  }
});
$("upload").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const button = form.querySelector("button");
  button.disabled = true;
  $("upload-status").textContent = "Uploading…";
  try {
    const { id } = await api("/api/jobs", { method: "POST", body: new FormData(form) });
    $("upload-status").textContent = "";
    form.reset();
    await openJob(id);
  } catch (error) {
    $("upload-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

const linked = location.hash.slice(1);
if (/^[0-9a-f]{12}$/.test(linked)) openJob(linked).catch(() => loadLibrary());
else loadLibrary().catch((error) => { $("empty").textContent = `Could not load the library: ${error.message}`; });
