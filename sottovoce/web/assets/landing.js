"use strict";

// Every line on this page is read from the live library or from the measured
// benchmark (evidence.json): real output, not copy.
const LESSON = "Moon Phases (NASA STEMonstrations)";
const LOOP = [40, 120]; // seconds of the lesson the hero plays, in lesson time
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const AIRED = new Set(["verified", "approved"]);

const $ = (id) => document.getElementById(id);
const clock = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function reveal() {
  const seen = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add("is-in");
      seen.unobserve(entry.target);
    }
  }, { threshold: 0.18 });
  document.querySelectorAll("[data-reveal]:not(.is-in)").forEach((node) => seen.observe(node));
}

function chip(claim, i, animate = true) {
  const li = document.createElement("li");
  li.className = `chip ${claim.verdict}${animate && !reduced ? " pop" : ""}`;
  li.style.setProperty("--i", i);
  li.textContent = claim.text;
  return li;
}

async function lesson() {
  const jobs = await (await fetch("/api/jobs")).json();
  const job = jobs.find((j) => j.status === "done" && j.title === LESSON) || jobs.find((j) => j.status === "done");
  return job ? (await fetch(`/api/jobs/${job.id}`)).json() : null;
}

// A held lesson is longer than the original: every aired line that runs past
// its pause freezes the picture. Same rule as export.py.
function timeMap(cues) {
  const holds = cues
    .filter((c) => AIRED.has(c.status) && c.audio && c.seconds > c.end - c.start)
    .map((c) => [c.end, c.seconds - (c.end - c.start) + 0.3]);
  return (t) => t + holds.filter(([at]) => at <= t).reduce((sum, [, extra]) => sum + extra, 0);
}

const aired = (job) => job.script.cues.filter((c) => c.line && AIRED.has(c.status));
const teacherSaid = (cue) => cue.focus || cue.before.split(/(?<=[.?!])\s+/).slice(-1)[0] || "";

function hero(job) {
  const video = $("hero-video");
  const cues = aired(job);
  const shift = timeMap(job.script.cues);
  let mode = "with";
  let shown = null;
  const toVideo = (t) => (mode === "with" ? shift(t) : t);
  const toLesson = (vt) => {
    if (mode === "without") return vt;
    let t = vt;
    for (let i = 0; i < 4; i++) t = vt - (shift(t) - t);
    return t;
  };

  const render = (t) => {
    // `t` is in lesson time: the line the child is hearing, or missing.
    const cue = [...cues].reverse().find((c) => c.start <= t) || cues[0];
    if (!cue || cue === shown) return;
    shown = cue;
    if (mode === "with") {
      $("hero-label").textContent = "Sottovoce says, while the lesson waits";
      $("hero-line").textContent = cue.line;
      $("hero-status").hidden = false;
      $("hero-status").textContent = cue.status;
      $("hero-chips").replaceChildren(...cue.claims.map((c, i) => chip(c, i)));
      $("hero-foot").textContent = `${clock(cue.start)} · Written by Gemma 4 and checked by Qwen3.8 on AMD Instinct GPUs.`;
    } else {
      $("hero-label").textContent = "A blind child hears only the teacher";
      $("hero-line").textContent = `"${teacherSaid(cue)}"`;
      $("hero-status").hidden = true;
      $("hero-chips").replaceChildren();
      $("hero-foot").textContent = "…and never finds out what was on the screen.";
    }
  };

  const load = (lessonTime = LOOP[0]) => {
    video.src = `/files/${job.id}/${mode === "with" ? "described" : "source"}`;
    video.addEventListener("loadedmetadata", () => { video.currentTime = toVideo(lessonTime); }, { once: true });
    shown = null;
    render(lessonTime + 1.5);
    if (!reduced) video.play().catch(() => {});
  };

  video.addEventListener("timeupdate", () => {
    const t = toLesson(video.currentTime);
    if (t >= LOOP[1] || t < LOOP[0] - 1) { video.currentTime = toVideo(LOOP[0]); return; }
    render(t);
  });
  document.querySelectorAll(".player-tabs .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.dataset.mode === mode) return;
      document.querySelectorAll(".player-tabs .tab").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
      const at = toLesson(video.currentTime || 0);
      mode = tab.dataset.mode;
      load(Math.max(at, LOOP[0]));
    });
  });
  $("hero-sound").addEventListener("click", (event) => {
    video.muted = !video.muted;
    event.currentTarget.setAttribute("aria-pressed", String(!video.muted));
    event.currentTarget.textContent = video.muted ? "Turn on sound" : "Sound on";
    if (video.paused) video.play().catch(() => {});
  });
  if (reduced) video.controls = true;
  new IntersectionObserver(([entry]) => {
    if (reduced) return;
    if (entry.isIntersecting) video.play().catch(() => {});
    else video.pause();
  }, { threshold: 0.25 }).observe(video);
  load();
}

function hear(job) {
  // Moments where the teacher points come first, then the catch-up lines.
  const cues = aired(job).filter((c) => c.start > 30 && c.start < job.script.duration - 30);
  const picked = [...cues.filter((c) => c.focus), ...cues.filter((c) => !c.focus && c.end - c.start < 0.1)]
    .slice(0, 3)
    .sort((a, b) => a.start - b.start);
  let playing = null;
  $("hear-list").replaceChildren(...picked.map((cue) => {
    const audio = new Audio(`/files/${job.id}/audio/${cue.audio}`);
    audio.preload = "none";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-ghost btn-small";
    button.textContent = "Play";
    button.addEventListener("click", () => {
      if (playing && playing !== audio) { playing.pause(); playing.currentTime = 0; }
      document.querySelectorAll("#hear-list .btn").forEach((b) => { if (b !== button) b.textContent = "Play"; });
      if (audio.paused) { audio.play(); playing = audio; button.textContent = "Playing"; }
      else { audio.pause(); audio.currentTime = 0; button.textContent = "Play"; }
    });
    audio.addEventListener("ended", () => { button.textContent = "Play"; });

    const li = document.createElement("li");
    li.className = "card hear-item";
    li.setAttribute("data-reveal", "");
    li.innerHTML = `
      <div class="hear-row"><span class="who">Teacher · ${clock(cue.start)}</span><p class="said"></p></div>
      <div class="hear-row"><span class="who accent">Lesson pauses · Sottovoce</span><div><p class="line"></p><ul class="chips"></ul></div></div>`;
    li.querySelector(".said").textContent = `"${teacherSaid(cue)}"`;
    li.querySelector(".line").textContent = cue.line;
    li.querySelector(".chips").replaceChildren(...cue.claims.map((c, i) => chip(c, i, false)));
    li.querySelector(".hear-row:last-child > div").append(button);
    return li;
  }));
  reveal();
}

async function evidence() {
  const e = await (await fetch("/assets/evidence.json")).json();
  $("n-caught").textContent = `${Math.round((e.caught / e.planted) * 100)}%`;
  $("n-caught-note").textContent = `${e.caught} of ${e.planted}, two NASA lessons`;
  $("n-false").textContent = String(e.false_alarms);
  $("n-false-note").textContent = `of ${e.originals} correct lines`;
  $("n-cost").textContent = `$${e.cost_per_minute.toFixed(4)}`;
  $("n-lines").textContent = `${e.verified}/${e.lines}`;
  $("n-lines-note").textContent = `${e.pointing} right after the teacher pointed`;
  $("faq-accuracy").textContent = `On two NASA lessons the checker caught ${e.caught} of ${e.planted} planted errors and wrongly flagged ${e.false_alarms} of ${e.originals} correct lines. Nothing reaches a child unless the checker verified it or a teacher approved it.`;
  const x = e.example;
  $("checker-note").textContent = `Here, ${x.change}. The checker caught it.`;
  $("planted-line").textContent = x.planted;
  $("planted-chips").replaceChildren(...x.problems.map((p, i) => chip({ text: p, verdict: "contradicted" }, i, false)));
  $("real-line").textContent = x.original;
  $("real-chips").replaceChildren(...x.claims.map((c, i) => chip(c, i + 1, false)));
}

reveal();
evidence().catch(() => {});
lesson()
  .then((job) => {
    if (!job) { $("hero-line").textContent = "The sample lesson is not in the library yet."; return; }
    hero(job);
    hear(job);
  })
  .catch(() => { $("hero-line").textContent = "The live library could not be reached."; });
