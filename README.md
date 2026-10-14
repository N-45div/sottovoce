# Sottovoce

**Audio description that fits the pauses and checks its own facts.** Two vision models on AMD Instinct GPUs write and cross-check every line. A person approves anything the checker cannot confirm. The models cost under a tenth of a cent per minute of video.

**Live app: https://sottovoce-408280170923.europe-west8.run.app**

Audio description is the voice that tells blind and low-vision viewers what is on screen, in the pauses between the dialogue. In 2025, RAI's three main channels audio-described 1,848 hours, about 10% of their airtime, against 17,786 hours with subtitles (AGCOM, 2026 annual report). RAI's 2023–2028 service contract commits to extending subtitles and audio description to its thematic channels "through the use of artificial intelligence", from 20% of programming in 2025 to 60% in 2029.

The obstacle is cost. A human describer costs about $7–35 per minute (US list prices). AI audio-description services charge about $1 per minute, but none that we found publishes how it checks that its descriptions are true.

Sottovoce does the work and keeps a person in charge of it:

1. **Finds the pauses.** It transcribes the dialogue with word timings (faster-whisper), so a description never talks over anyone. Long silent scenes are split, so they are described as they unfold.
2. **Looks at the right frames.** It finds the shot changes and sends a keyframe from every shot inside each pause.
3. **Writes a line, then checks it with a second model.**
   - Gemma 4 writes the line in the house style, inside a word budget.
   - Qwen3.8 is from a different family, so the two don't share blind spots. It splits the line into one claim per person, object, place, colour and quoted text, and checks each against the frames.
   - A contradicted or unconfirmed claim goes back for a rewrite. A line that still fails after three rounds goes to a person.
4. **Voices it to fit.** Google Cloud Text-to-Speech reads the line. Every take is measured and sped up slightly if needed. A line that still runs over its pause goes to a person, so it never talks over the dialogue.
5. **Mixes it like a broadcaster.** It lowers the programme under each line and exports an MP4 with the description mixed in, the narration as a separate track, and a WebVTT `kind="descriptions"` track.

## Three audiences

| Audience | What it does |
|---|---|
| Italian (`it`) | Standard audio description for blind and low-vision viewers. |
| English (`en`) | For visitors who don't speak Italian. On-screen Italian text is read in translation. |
| Extended (`extended`) | Extended audio description (WCAG success criterion 1.2.7): when a scene needs more words than the pause allows, the picture holds until the line ends. |

The house style reads short on-screen text aloud, such as titles, signs and headlines. It does not describe people's skin colour or ethnicity.

## Measured on a real film

All numbers come from the first 150 seconds of *Tears of Steel*, run through the real models.

| | Italian | English | Extended |
|---|---|---|---|
| Lines written | 16 | 16 | 16 |
| Verified by the checker | 16 | 16 | 16 |
| Lines that fit their pause | 16 | 16 | 16 (the picture held 10 times, +27.6 s) |
| Time for 150 s of video | 299 s | 410 s | 522 s |
| Model cost on AMD Token Factory, per minute of video | $0.00064 | $0.00080 | $0.00094 |

**How well the checker catches errors.** For every line above, the benchmark planted one false detail, such as "train engines" for rocket engines, an umbrella for a rifle, a forest for a city, or a child for a man. It then asked the checker about both the planted line and the original.

| Writer, checker | Planted errors caught | Correct lines wrongly flagged |
|---|---|---|
| DeepSeek-V4-Flash-Vision, first checker (loose claims) | 17 of 28 (61%) | 0 of 28 |
| DeepSeek-V4-Flash-Vision, current checker (one claim per noun) | 22 of 28 (79%) | 1 of 28 |
| **Gemma 4, current checker** | **28 of 32 (88%)** | **0 of 32** |

It still misses some swaps that leave the picture plausible, such as a beach for the deck of a ship, or a boat for a balcony. 32 lines is a small sample, so read these as an early measurement, not a guarantee. That is why every line stays editable and a person approves anything the checker cannot confirm.

## Where it runs

- **AMD:** every vision call goes to AMD Token Factory, which runs open models on AMD Instinct GPUs.
  - The writer is Gemma-4-31B-IT, with DeepSeek-V4-Flash-Vision as its backup.
  - The checker is Qwen3.8-27B with low reasoning effort, with Qwen3.8-Flash as its backup.
  - On Qwen3.8-27B, default reasoning took 35 s per check with the same verdicts. Thinking switched off took 4.5 s, but it rejected a true claim.
- **Google:**
  - Gemma 4 writes every line.
  - The describe-check-rewrite loop is a [Google ADK](https://google.github.io/adk-docs/) agent: two `LlmAgent`s under a custom `BaseAgent`, each on an ADK `FallbackModel`. Whether a line passes is decided by code, not by a model.
  - The same agent is served over A2A at `/a2a`, so other agents can send keyframes and get a checked line back.
  - The voices are Google Cloud Text-to-Speech, Chirp 3 HD.
  - The app runs on Cloud Run in Milan, with its library in Cloud Storage.

## Run it

```bash
pip install -e .
export AMD_API_KEY=...                 # AMD Token Factory key
export GOOGLE_CLOUD_PROJECT=...        # a project with Text-to-Speech enabled
python -m sottovoce film.mp4 --audience it --out outputs/
uvicorn sottovoce.server:app --port 8080   # the web app
```

The web app takes an upload, shows each line as it is written and checked, plays the result with audio description on or off, and lets a describer edit or approve any line. An edited line is checked against the frames, re-voiced and re-mixed.

`docker build .` builds the container that runs on Cloud Run.

## Tests

`pytest` runs the logic tests. To also run the live tests against the real models and real film frames:

1. Fetch the test clip: `python scripts/fetch_test_clip.py media`, which saves the first 150 s of *Tears of Steel*.
2. Set `AMD_API_KEY` and `GOOGLE_CLOUD_PROJECT`.

The live tests include a planted-error test and an A2A round trip. The tests use no mocks.

`python -m sottovoce.bench outputs/script.json` measures the checker. It plants one false detail in every verified line (a swapped object, person, place or colour, or an added object) and reports how many it catches, and how often it flags a line that was right.

## Credits

The test film is *Tears of Steel* (CC BY 3.0, © Blender Foundation, mango.blender.org).

## License

MIT
