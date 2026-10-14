# Sottovoce

**Blind children hear the lesson. Sottovoce tells them what is on the board.**

**Live app: https://sottovoce-408280170923.europe-west8.run.app**

When a teacher in a video says "look at this", a blind child is left out. The formula on the board, the arrow on a diagram and the colour change in an experiment all reach only the eyes. Audio description fixes that: a voice says what is on screen. But it takes a trained describer, so almost no educational video has it. In a national US survey, educators of blind students said less than 5% of the educational videos they use were described (DCMP).

Sottovoce describes lessons for blind and low-vision children:

1. **Listens to the teacher.** It transcribes the lesson with word timings (faster-whisper) and finds every moment the teacher points at the screen: "look at this", "you can see", "guardate", "ecco".
2. **Pauses when it matters.**
   - Right after the teacher points.
   - In natural pauses.
   - Whenever the picture keeps changing with nothing described for 25 seconds.

   The video holds while the line is spoken (extended audio description, WCAG 1.2.7), on the frame being described, so the teacher is never talked over.
3. **Writes for a child.** Gemma 4 reads the board, numbers and formulas exactly, explains a diagram by how it is built, and uses short sentences and simple words.
4. **Checks every claim.** Qwen3.8, a different model family, splits each line into claims and checks each one against the frames. A wrong number would teach a child something false, so a contradicted claim goes back for a rewrite. A line that still fails goes to the teacher.
5. **Speaks it.** Google Cloud Text-to-Speech (Chirp 3 HD), in Italian or English.
6. **The teacher approves.** Only lines the checker verified or a teacher approved reach the child. An edited line is checked, re-voiced and re-mixed.

You get the described lesson as MP4, the narration as a separate track, and a WebVTT `kind="descriptions"` track.

## Measured on two real lessons

Two NASA STEMonstrations lessons for children (*Moon Phases*, 4:21, and *Area and Volume*, 4:09; public domain), run through the live models:

| | |
|---|---|
| Lines written | 32 |
| Verified by the checker | 32 |
| Lines placed right after the teacher pointed | 5 |
| Planted errors caught (a changed number, cube to sphere, Earth to Mars, left to right, moon to sun…) | **24 of 32 (75%)** |
| Correct lines wrongly flagged | **0 of 32** |
| Model cost on AMD Token Factory | **$0.00053 per minute of lesson** |

Of the 8 planted errors the checker missed, 5 swapped "space station" for "space ship", which a frame can barely tell apart. 32 lines is a small sample, so read these as an early measurement, not a guarantee.

Examples of real lines from *Moon Phases*:
- After *"let's take a look at where the space station is…"*: "A diagram shows the Earth and the International Space Station orbiting it."
- On screen: "A drawing of Earth and the moon. Text reads: 'THE MOON IS 238,855 MILES AWAY'."
- The demonstration: "A white sphere is held up. The left side is lit."

The engine was first measured on 150 s of *Tears of Steel*. On 32 film lines, Gemma 4 writing and Qwen3.8 checking caught 28 of 32 planted errors, with 0 false alarms.

## Where it runs

- **AMD:** every vision call goes to AMD Token Factory, which runs open models on AMD Instinct GPUs.
  - The writer is Gemma-4-31B-IT, with DeepSeek-V4-Flash-Vision as backup.
  - The checker is Qwen3.8-27B at low reasoning effort, with Qwen3.8-Flash as backup.
- **Google:**
  - Gemma 4 writes every line.
  - The describe-check-rewrite loop is a [Google ADK](https://google.github.io/adk-docs/) agent: two `LlmAgent`s under a custom `BaseAgent`, each on an ADK `FallbackModel`. Whether a line passes is decided by code, not by a model.
  - The same agent is served over A2A at `/a2a`, so a learning platform can send keyframes, with what the teacher said, and get a checked line back.
  - Voices come from Google Cloud Text-to-Speech.
  - The app runs on Cloud Run in Milan, with its library in Cloud Storage.

## Run it

```bash
pip install -e .
export AMD_API_KEY=...                 # AMD Token Factory key
export GOOGLE_CLOUD_PROJECT=...        # a project with Text-to-Speech enabled
python -m sottovoce lesson.mp4 --audience en --out outputs/   # or --audience it
uvicorn sottovoce.server:app --port 8080                      # the web app
```

`docker build .` builds the container that runs on Cloud Run.

## Tests

`pytest` runs the logic tests. To also run the live tests against the real models and real frames:

1. Fetch the test clip: `python scripts/fetch_test_clip.py media`.
2. Set `AMD_API_KEY` and `GOOGLE_CLOUD_PROJECT`.

The live tests include a planted-error test and an A2A round trip. The tests use no mocks.

`python -m sottovoce.bench outputs/script.json` measures the checker. It plants one false detail in every verified line (a changed number, or a swapped object, place or colour) and reports how many it catches, and how often it flags a line that was right.

## Credits

- Lessons: NASA STEMonstrations, *Moon Phases* and *Area and Volume* (NASA, public domain).
- Engine test film: *Tears of Steel* (CC BY 3.0, © Blender Foundation, mango.blender.org).

## License

MIT
