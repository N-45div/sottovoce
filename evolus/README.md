# Sottovoce on Evolus: the request desk

Sottovoce's request desk runs on [Evolus](https://evolus.ai). A teacher writes in plain words ("please describe this for my 7-year-old, in Italian: <link>"), and the desk starts the described lesson, asks for what is missing, answers questions about the rules, and writes easy-read notes when a lesson is done.

The agents think on AMD. Gemma-4-31B-IT on AMD Token Factory (an OpenAI-compatible API serving open models on AMD Instinct GPUs) is connected as the workspace's own model, with DeepSeek-V4.1-Flash as its fallback. The workspace runs its agents and workflow AI steps only on its own models, and if Token Factory does not answer, a request stops; it never moves to another model.

Evolus's own services run on Evolus models and use the workspace's credits:
- the `translate` AI Tool;
- the library's search index;
- safety checks.

## What is in the workspace

- **Agents**, both on Gemma 4 on AMD:
  - **Sottovoce request desk** reads requests and answers teachers. It has:
    - the knowledge library;
    - a "Lesson request" output structure;
    - the Sottovoce connector;
    - the notes agent as a sub-agent.
  - **Sottovoce lesson notes** writes easy-read notes for the child's age from a lesson's transcript.
- **Knowledge library** "Sottovoce request desk": the three documents in [knowledge/](knowledge/), one chunk per section:
  - what WCAG, the ADA and Italian and EU law ask for;
  - how Sottovoce works;
  - how the desk handles a request.
- **Workflow "Describe a lesson"**:
  1. Read the request: the desk agent, with its output structure.
  2. Check the request: a script ([check.js](setup/check.js)).
  3. Ready?: an If.
  4. Start the described lesson: a webhook to Sottovoce's `POST /api/jobs` with the video link.
  5. Reply to the teacher: a script ([reply.js](setup/reply.js)).
  6. Output.
- **Workflow "Lesson notes"**, with the parameters `language`, `other_language` and `age`:
  1. Write the notes: the notes agent.
  2. Translate the notes: the `translate` AI Tool.
  3. Put them together: a script.
  4. Output.
- **Connector "Sottovoce"**: Sottovoce's own MCP server at `/mcp/` ([connector.py](../sottovoce/connector.py)), with five tools:
  - `describe_lesson`
  - `lesson_status`
  - `lines_to_review`
  - `lesson_transcript`
  - `list_lessons`
  
  From a chat, the desk agent can start a lesson, follow it and answer what was on screen.
- **Chat widget** on the landing page: the desk agent, limited to Sottovoce's own origins.

## How Sottovoce drives it

Sottovoce calls Evolus through its APIs ([desk.py](../sottovoce/desk.py)):

- **Requests:** a message with a video link runs "Describe a lesson" through `POST /api/v1/workflows/{id}/execute`. The page follows the execution with `GET /api/v1/workflows/{id}/executions/{executionId}`.
- **Questions:** any other message goes to the desk agent through the OpenAI-compatible `POST /v1/chat/completions`, with the model `<applicationId>:<agentId>`.
- **Notes:** when a lesson is done, Sottovoce writes its descriptive transcript (the teacher's words and every aired line, in order, which is WCAG 1.2.8's text alternative). It runs "Lesson notes" on it and offers both as downloads.

Settings: `EVOLUS_API_KEY`, `EVOLUS_APP_ID`, `EVOLUS_DESK_WORKFLOW`, `EVOLUS_DESK_AGENT` and `EVOLUS_NOTES_WORKFLOW`. Without them, the desk says it is not set up and lessons still get their transcript.

## Rebuild it

The scripts in [setup/](setup/) build the workspace through the Evolus MCP server:

1. Connect the model in the portal: **Your models → Connect your own server**. Use the base URL `https://developer.amd.com.cn/radeon/api/v1` and your Token Factory key, and pick Gemma-4-31B-IT and DeepSeek-V4.1-Flash. An application key cannot do this step.
2. Run the scripts:

```bash
export EVOLUS_API_KEY=... EVOLUS_APP_ID=...
cd evolus/setup
python chunks.py                                                  # the knowledge library
python make_agent.py own/gemma-4-31b-it own/deepseek-v4.1-flash   # the desk agent and its output structure
python build_desk.py                                              # "Describe a lesson"
python build_notes.py                                             # the notes agent, its sub-agent link, "Lesson notes"
python run_desk.py "Please describe https://.../lesson.mp4 for my 7-year-old, in English"
```

3. Add the connector and the widget in the portal:
   - **Connections → Custom connection**: HTTP, `https://<your Sottovoce>/mcp/`. Then attach it to the desk agent.
   - **Website widget**: pick the desk agent, and list your site's origins.

The IDs the scripts create go to `setup/desk.json`, which is not committed.

## Measured on the live workspace (Oct 17)

These are single runs, not averages:

| Step | Time |
|---|---|
| A request with its age missing, answered with one reply asking for it | 9 s |
| A question answered from the library | 10-15 s |
| Easy-read notes for *Moon Phases*, written and translated | 60 s |
| Through the connector, the agent started a lesson in Italian for ages 5-8 (all 16 lines verified) | 13.5 s |
