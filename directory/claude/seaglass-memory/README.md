# Seaglass Memory

Seaglass keeps a memory of your work that you, your team and the AI tools you
connect can read and add to. With this plugin, Claude can search that memory
when you ask about a person, project or past decision, and save the decisions,
preferences and corrections you state, saying in one line what it saved. Seaglass
files what is saved onto wiki pages you can read, edit and share in the Seaglass
web app.

## What the plugin contains

- **One remote connector**, the Seaglass MCP server at
  `https://api-stg.seaglassai.com/mcp`. It is the only endpoint the plugin calls.
  You sign in to Seaglass in your browser the first time Claude connects; the
  plugin stores no credential of its own.
- **Three skills**: `seaglass-memory` (when to search and when to save),
  `recall` (load what Seaglass holds on a topic, when you ask) and `status`
  (whether this client is connected, and the one step to fix it if not).

The plugin contains no hooks, scripts or binaries, and runs nothing on your
machine.

## What Seaglass receives

Only what a tool call carries: the search terms Claude sends, the memories and
documents it saves, and the documents you choose to import from a source you
connected. The plugin does not read your conversation history or Claude's own
memory, and it reads a project's files only if you accept Seaglass's offer to
import that project. What Seaglass does with that data is in the
[privacy policy](https://stg.seaglassai.com/privacy).

## Try it

- "What did we decide about the launch plan?"
- "Remember that I prefer short status updates."
- "What do we know about the Atlas project?"

## Support

Help, account and data questions: [https://stg.seaglassai.com/support](https://stg.seaglassai.com/support).
Terms: [https://stg.seaglassai.com/terms](https://stg.seaglassai.com/terms).

Licensed under the Apache License 2.0; see `LICENSE`.
