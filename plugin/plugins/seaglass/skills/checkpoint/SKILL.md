---
name: checkpoint
description: Summarize what was memory-worthy in the current conversation and store it to Seaglass via the MCP server. Use when the user types /checkpoint, says "save what we talked about", "checkpoint this session", "store today's progress", or at the natural end of a long capture-worthy session.
disable-model-invocation: true
argument-hint: [optional topic to scope the checkpoint]
---

# Seaglass session checkpoint

Walk back through the current conversation, identify the discrete things
worth remembering, and write them to Seaglass with full framing.

This is the explicit alternative to a `Stop` hook. It exists because Cowork
and some other clients don't fire plugin hooks; the user (or you, at the
end of a meaningful session) invokes this to flush the session into
durable memory.

## What to capture

Scope: the entire current conversation. If `$ARGUMENTS` is non-empty, scope
narrows to memories related to that topic.

Capture:

- People mentioned with concrete attributes (role, project, decision,
  preference).
- Projects, tools, initiatives discussed with substantive content.
- Decisions the user made.
- Preferences expressed ("I prefer async reviews", "use vitest, not jest").
- Corrections to prior facts (use `flag_memory` for those, not a new write).
- Pasted documents, specs, or transcripts the user wanted kept (use
  `store_document`).

Do **not** capture:

- Small talk, greetings, "thanks", debugging chatter without resolution.
- Transient task state ("we're on step 3").
- Code snippets unless the user asked to remember them.
- Things you already saw in `search` calls earlier this session
  (avoid re-storing what's already there).

## How to write each one

Use the existing `seaglass-memory` skill's tool calls (`store_memory`,
`store_document`). Two requirements specific to checkpoint mode:

1. **Density.** 200–2000 chars per memory, with the surrounding scaffolding —
   when, who else was involved, the rationale, what makes it notable. Five
   rich memories beat fifteen one-liners.

2. **Capture context.** Every write should include `capture_context` (one
   to two sentences) describing what the conversation knew that the bare
   content alone wouldn't — the framing, the preceding topic, why the user
   surfaced it. The server uses this to make extracted memories richer.

   ```json
   {
     "content": "Sarah Chen confirmed as PM of Project Nova at the April 15 kickoff. Previously CTO at Acme; the user noted this came up alongside her budget pushback the week before.",
     "primary_page": "people/sarah-chen",
     "links": {"projects": ["projects/project-nova"], "topics": ["Q3 launch"]},
     "capture_context": "End-of-session checkpoint after a 30-minute review of the Nova staffing plan; user wanted Sarah's role and the Acme background preserved together."
   }
   ```

## Avoid double-stores

If a memory you're about to write closely matches something already in
Seaglass (you saw it via `search` this session, or you wrote it
earlier this same session), skip it. If it adds new context to an existing
memory, prefer `flag_memory` with `flag_outdated` on the old one and a
fresh write — or use `store_memory` with `source_type: annotation` and
`source_memory_id` pointing at the original.

## Sensitivity

Respect anything the user said about privacy:

- Inline `<private>...</private>` blocks pass through verbatim — server
  forces `sensitivity: private`.
- "Off the record", "between us", "don't remember this" → set
  `sensitivity: private` on the write.
- Compensation, health, personal-life details → `sensitivity: sensitive`.

The full matrix lives in the `seaglass-memory` skill's sensitivity
reference doc; load that skill if you need the detailed semantics.

## Report back

After all writes complete, give the user a short summary:

```
Stored 4 memories and 1 document:
  - Sarah Chen (page_01...) — Nova PM confirmation + Acme background
  - Project Nova (page_01...) — April 15 kickoff outcomes
  - Q3 launch (page_01...) — budget pushback context
  - User preference (memory_01...) — async reviews over sync
  - Nova v3 spec (document_01...) — pasted, supersedes Tuesday's draft
Skipped 2 items already in Seaglass.
```

Keep it tight — IDs and one-line rationales, no ceremony. If anything
looked ambiguous (multiple people named Sarah, unclear which project), say
so explicitly and ask the user before writing.

## What you MUST NOT do

- Don't dump the raw transcript as a single document. Capture distinct
  observations.
- Don't pass identity fields (`user_id`, `agent_id`, `session_id`) — the
  server fills these from auth context.
- Don't write everything you ever saw — be selective. The wiki is the
  product; noise hurts every future read.
