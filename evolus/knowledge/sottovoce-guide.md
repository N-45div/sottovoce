# Sottovoce: how a described lesson is made

Sottovoce describes lesson videos for blind and low-vision children. It is live at https://sottovoce-ai.web.app.

## What a teacher sends

- A lesson video: an upload, or an https link to the video file. Up to 5 minutes and 30 MB on the hosted app.
- The language: English or Italian.
- The age: 5-8, 8-13 or 14-18. The same pauses and checks, told in different words for each age.

## What happens

1. Sottovoce listens to the teacher and finds every moment they point at the screen ("look at this", "guardate").
2. It pauses the lesson where a description is needed: right after the teacher points, in natural pauses, and when the picture changes with nothing said. The picture holds on the frame being described, so a line longer than the teacher's pause is never cut or rushed.
3. One model writes each line in simple words, reading text, numbers and formulas exactly.
4. A second model, from a different family, checks every claim in the line against the frames. A wrong claim goes back for a rewrite.
5. Only lines the checker verified, or a teacher approved, reach the child.

## What the teacher gets back

- The described lesson as an MP4, the narration as a separate WAV track, and a WebVTT descriptions file for any player.
- A page listing every line with its checked claims. A line marked "needs review" is not aired until a teacher approves or edits it; an edited line is checked and voiced again.
- It usually takes a few minutes for a 4-minute lesson.

## While the child watches

- **Ask:** the child pauses and asks about the picture by voice. The answer comes from the frame on screen, checked before it is spoken. If the picture does not show it, Sottovoce says so and suggests asking the teacher. The recording of the question is deleted as soon as it is transcribed.
- **Where is everything?** Each thing in the picture is said from where it is, left or right, so a child with headphones hears the layout of a diagram.
- Keys: Space plays or pauses, hold A to ask, M for where things are, R to hear the last answer again.

## Models and where they run

Open models on AMD Instinct GPUs write and check the lines. The agent loop is built with Google's Agent Development Kit, voices come from Google Cloud Text-to-Speech, and the app runs on Google Cloud Run in Milan.

## Measured

On two NASA lessons for children, 32 of 32 lines were verified, and 5 were placed right after the teacher pointed. 24 of the 32 lines were longer than the teacher's pause, so the lesson waited 100 seconds over 8.5 minutes. With a false detail planted in every line, the checker caught most of them and the rest go to the teacher. The model cost is a fraction of a cent per minute of lesson.
