"use strict";

// Every line shown on this page is read from the live library: real output, not copy.
const FILM = "Tears of Steel (opening)";
const LOOP = [44, 117]; // seconds of the film the hero plays: titles, the lab, the snipers
const MOMENT = 53.77; // the scene the three audience cards compare
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

const $ = (id) => document.getElementById(id);
const clock = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function reveal() {
  const seen = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add("is-in");
      entry.target.querySelectorAll("[data-count]").forEach(countUp);
      if (entry.target.matches("[data-count]")) countUp(entry.target);
      seen.unobserve(entry.target);
    }
  }, { threshold: 0.18 });
  document.querySelectorAll("[data-reveal]").forEach((node) => seen.observe(node));
}

function countUp(node) {
  const target = Number(node.dataset.count);
  const suffix = node.dataset.suffix || "";
  if (reduced || !target) { node.textContent = `${target}${suffix}`; return; }
  const start = performance.now();
  const tick = (now) => {
    const k = Math.min(1, (now - start) / 900);
    node.textContent = `${Math.round(target * (1 - (1 - k) ** 3))}${suffix}`;
    if (k < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

async function library() {
  const jobs = await (await fetch("/api/jobs")).json();
  const pick = (audience) =>
    jobs.find((j) => j.status === "done" && j.audience === audience && j.title === FILM) ||
    jobs.find((j) => j.status === "done" && j.audience === audience);
  const out = {};
  for (const audience of ["it", "en", "extended"]) {
    const job = pick(audience);
    if (job) out[audience] = await (await fetch(`/api/jobs/${job.id}`)).json();
  }
  return out;
}

function chip(claim, i) {
  const li = document.createElement("li");
  li.className = `chip ${claim.verdict}${reduced ? "" : " pop"}`;
  li.style.setProperty("--i", i);
  li.textContent = claim.text;
  return li;
}

function hero(jobs) {
  const video = $("hero-video");
  let audience = jobs.it ? "it" : Object.keys(jobs)[0];
  if (!audience) { $("hero-line").textContent = "The sample film is not in the library yet."; return; }
  let shown = null;

  const load = (keepTime) => {
    const at = keepTime ? video.currentTime : LOOP[0];
    video.src = `/files/${jobs[audience].id}/described`;
    video.addEventListener("loadedmetadata", () => { video.currentTime = at; }, { once: true });
    shown = null;
    if (!reduced) video.play().catch(() => {});
  };

  const show = () => {
    const t = video.currentTime;
    if (t >= LOOP[1] || t < LOOP[0] - 1) { video.currentTime = LOOP[0]; return; }
    render(t);
  };

  // The line for time `t`, straight from the script. Runs before the film has
  // buffered too, so the card never sits on a loading message.
  const render = (t) => {
    const cues = jobs[audience].script.cues.filter((c) => c.line && c.status !== "needs_review");
    const cue = [...cues].reverse().find((c) => c.start <= t) || cues[0];
    if (!cue || cue === shown) return;
    shown = cue;
    $("hero-line").textContent = cue.line;
    $("hero-status").hidden = false;
    $("hero-status").textContent = cue.status;
    $("hero-status").className = `badge ${cue.status}`;
    $("hero-time").textContent = `${clock(cue.start)} · spoken in ${cue.seconds.toFixed(1)} s of a ${(cue.end - cue.start).toFixed(1)} s pause`;
    $("hero-chips").replaceChildren(...cue.claims.map(chip));
  };

  video.addEventListener("timeupdate", show);
  document.querySelectorAll(".player-tabs .tab").forEach((tab) => {
    if (!jobs[tab.dataset.audience]) { tab.hidden = true; return; }
    tab.addEventListener("click", () => {
      document.querySelectorAll(".player-tabs .tab").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
      audience = tab.dataset.audience;
      load(true);
      render(Math.max(video.currentTime, LOOP[0]));
    });
  });
  $("hero-sound").addEventListener("click", (event) => {
    video.muted = !video.muted;
    event.currentTarget.setAttribute("aria-pressed", String(!video.muted));
    event.currentTarget.textContent = video.muted ? "Listen with description" : "Sound on";
    if (video.paused) video.play().catch(() => {});
  });
  if (reduced) video.controls = true;

  // Only stream while the hero is on screen.
  new IntersectionObserver(([entry]) => {
    if (reduced) return;
    if (entry.isIntersecting) video.play().catch(() => {});
    else video.pause();
  }, { threshold: 0.25 }).observe(video);
  load(false);
  render(LOOP[0] + 1.5); // the first line inside the loop, before the film has buffered
}

function audiences(jobs) {
  let playing = null;
  document.querySelectorAll(".audience").forEach((card) => {
    const job = jobs[card.dataset.audience];
    if (!job) return;
    const cues = job.script.cues.filter((c) => c.line);
    const cue = cues.reduce((best, c) => (Math.abs(c.start - MOMENT) < Math.abs(best.start - MOMENT) ? c : best), cues[0]);
    if (!cue) return;
    const pause = cue.end - cue.start;
    card.querySelector(".audience-line").textContent = cue.line;
    card.querySelector(".audience-meta").textContent = card.dataset.audience === "extended"
      ? `Spoken in ${cue.seconds.toFixed(1)} s. The picture holds ${Math.max(0, cue.seconds - pause + 0.3).toFixed(1)} s so nothing is cut.`
      : `Spoken in ${cue.seconds.toFixed(1)} s, inside a ${pause.toFixed(1)} s pause.`;
    const button = card.querySelector(".play");
    const audio = new Audio(`/files/${job.id}/audio/${cue.audio}`);
    audio.preload = "none";
    button.disabled = false;
    button.addEventListener("click", () => {
      if (playing && playing !== audio) { playing.pause(); playing.currentTime = 0; }
      document.querySelectorAll(".audience .play").forEach((b) => { if (b !== button) { b.classList.remove("is-playing"); b.textContent = "Play"; } });
      if (audio.paused) { audio.play(); playing = audio; button.classList.add("is-playing"); button.textContent = "Playing"; }
      else { audio.pause(); audio.currentTime = 0; button.classList.remove("is-playing"); button.textContent = "Play"; }
    });
    audio.addEventListener("ended", () => { button.classList.remove("is-playing"); button.textContent = "Play"; });
  });
}

reveal();
library()
  .then((jobs) => { hero(jobs); audiences(jobs); })
  .catch(() => { $("hero-line").textContent = "The live library could not be reached."; });
