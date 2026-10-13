# Sottovoce

**Audio description that fits the pauses and checks its own facts.** Two vision models on AMD Instinct GPUs write and cross-check every line, for about $0.0015 per minute of video. A human describer costs $15–75 per minute.

Audio description is the voice that tells blind and low-vision viewers what is on screen, in the pauses between the dialogue. Almost nobody gets it. In 2025, RAI's three main channels aired 1,848 hours of audio-described programming against 17,786 hours with subtitles (AGCOM, 2026 annual report). The reason is cost: a describer has to watch, write, time, record and mix every minute by hand.

Sottovoce does that work and keeps a person in charge of it:

1. **Finds the pauses.** It transcribes the dialogue with word timings (faster-whisper), so a description never talks over anyone. Long silent scenes are split, so they are described as they unfold.
2. **Looks at the right frames.** It finds the shot changes and sends a keyframe from every shot inside each pause.
3. **Writes a line, then checks it with a second model.** One vision model writes the line in the house style, inside a word budget. A second vision model, from a different family so the two don't share blind spots, splits the line into claims and checks each against the frames. A contradicted or unconfirmed claim goes back for a rewrite. A line that still fails after three rounds goes to a person.
4. **Voices it to fit.** Google Cloud Text-to-Speech reads the line. Every take is measured and sped up slightly if needed, and lines that still don't fit are flagged.
5. **Mixes it like a broadcaster.** It lowers the programme under each line and exports an MP4 with the description mixed in, the narration as a separate track, and a WebVTT `kind="descriptions"` track.

## Three audiences

| Audience | What it does |
|---|---|
| Italian (`it`) | Standard audio description for blind and low-vision viewers. |
| English (`en`) | For visitors who don't speak Italian. On-screen Italian text is translated. |
| Extended (`extended`) | Extended audio description (WCAG success criterion 1.2.7): when a scene needs more words than the pause allows, the picture holds until the line ends. |

## Measured on a real film

All numbers come from the first 150 seconds of *Tears of Steel*, run through the real models.

| | Italian | English |
|---|---|---|
| Lines written | 16 | 16 |
| Verified by the checker | 14 | 14 |
| Sent to a person | 2 | 2 |
| Lines that fit their pause | 16 | 16 |
| Time for 150 s of video | 232 s | 232 s |
| Model cost on AMD Token Factory | $0.0038 ($0.0015/min) | |

One of the English lines sent to a person quoted a newspaper headline as "ROBOTICIST KILLER ROBOTS". The checker refused it three times, because the headline on screen says something else. That is the point: a misquote reaches a person, not the audience.

**How well the checker catches errors.** For every verified line above, the benchmark planted one false detail, such as "train engines" for rocket engines, an umbrella for a rifle, or a child for a man. It then asked the checker about both the planted line and the original.

| Checker | Planted errors caught | Correct lines wrongly flagged |
|---|---|---|
| First version (loose claims) | 17 of 28 (61%) | 0 of 28 |
| Current (one claim per noun, colour, age and quoted text) | **22 of 28 (79%)** | 1 of 28 (4%) |

It still misses swaps the frames leave open to interpretation, such as "an industrial forest" for an industrial city, or a child for a small, distant figure. 28 lines is a small sample, so read these as an early measurement, not a guarantee. That is also why every line stays editable and a person approves anything the checker cannot confirm.

**Extended description** on the same clip: 16 lines, 15 verified. The picture held 10 times, adding 21 s to the 150 s clip.

## Where it runs

- **AMD:** every vision call goes to AMD Token Factory, which runs open models on AMD Instinct GPUs.
  - The writer is DeepSeek-V4-Flash-Vision.
  - The checker is Qwen3.8-27B with low reasoning effort. Default effort took 35 s per check with the same verdicts. Thinking off took 4.5 s, but it rejected a true claim.
- **Google:**
  - The describe-check-rewrite loop is a [Google ADK](https://google.github.io/adk-docs/) agent: two `LlmAgent`s under a custom `BaseAgent`. Whether a line passes is decided by code, not by a model.
  - The voices are Google Cloud Text-to-Speech, Chirp 3 HD.
  - The app runs on Cloud Run.

## Run it

```bash
pip install -e .
export AMD_API_KEY=...                 # AMD Token Factory key
export GOOGLE_CLOUD_PROJECT=...        # a project with Text-to-Speech enabled
python -m sottovoce film.mp4 --audience it --out outputs/
uvicorn sottovoce.server:app --port 8080   # the web app
```

The web app takes an upload, shows each line as it is written and checked, plays the result with audio description on or off, and lets a describer edit or approve any line. An edited line is checked against the frames, re-voiced and re-mixed.

## Tests

`pytest` runs the logic tests. With `AMD_API_KEY`, `GOOGLE_CLOUD_PROJECT` and the test clip present, it also runs live tests against the real models and real film frames, including a planted-error test. The tests use no mocks.

`python -m sottovoce.bench outputs/script.json` measures the checker. It plants one false detail in every verified line (a swapped object, person, place or colour, or an added object) and reports how many it catches, and how often it flags a line that was right.

## Credits

The test film is *Tears of Steel* (CC BY 3.0, © Blender Foundation, mango.blender.org).

## License

MIT
