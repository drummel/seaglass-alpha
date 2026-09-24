---
name: checkpoint
description: Capture, in one pass, what the current conversation produced that is worth remembering and is not in Seaglass yet. Use when the user types /checkpoint, says "save what we talked about", "checkpoint this session", "store today's progress", or when a substantive session is ending with things still uncaptured.
argument-hint: [optional topic to scope the checkpoint]
---

# Seaglass session checkpoint

Walk back through the conversation, find the distinct things worth remembering
that are not captured yet, and write them to Seaglass with their framing, all in
one pass.

It is the end-of-work backstop: the user can invoke it, and so can you, when a
substantive session is ending with things still uncaptured.

## What to capture

Scope: the whole conversation, or, when `$ARGUMENTS` is non-empty, what relates
to that topic.

- People mentioned with concrete attributes: role, project, decision, preference.
- Projects, tools, and initiatives discussed with substantive content.
- Decisions the user made, and preferences they expressed ("I prefer async
  reviews", "use vitest, not jest").
- Corrections to earlier facts, made as corrections (a newer fact that replaces
  the old one, or a retraction), not as a plain new write.
- Pasted documents, specs, or transcripts the user wanted kept, stored as
  documents.

Leave out what the core rules skip, plus debugging chatter that never resolved
and code the user didn't ask to keep.

## How to write each one

1. **One observation per memory, told in full.** Each memory is one fact, with
   the scaffolding that lets it stand alone later: when, who else was involved,
   the rationale, why it mattered. Five memories that each carry their context
   beat fifteen one-liners.
2. **Framing on every write.** Pass `capture_context`, a sentence or two saying
   what the conversation knew that the bare content does not: the preceding
   topic, why the user brought it up.

   For Ada's role, the content is "Ada Example confirmed as PM of Project
   Example at the April 15 kickoff. Previously CTO at Example Corp; the user
   noted this came up alongside her budget pushback the week before." and the
   capture context is "End-of-session checkpoint after a 30-minute review of the
   Project Example staffing plan; user wanted Ada's role and the Example Corp
   background preserved together." Ada is the primary page, and Project Example
   and the Q3 launch go in `links`.

## Avoid double-stores

Skip what is already in Seaglass: what you read this session, and what you wrote
earlier in it. When the new fact replaces an old one, make it the correcting
write (with `supersedes`), so the old row retires in the same call. When it only
adds context to an existing memory, attach it as an annotation (`source_type:
annotation` with `source_memory_id`).

## Report back

When the writes are done, give the user a short summary, built from what each
call's `receipt` says landed:

```
Stored 4 memories and 1 document:
  - Ada Example (page_01...): Project Example PM confirmation + Example Corp background
  - Project Example (page_01...): April 15 kickoff outcomes
  - Q3 launch (page_01...): budget pushback context
  - User preference (memory_01...): async reviews over sync
  - Project Example v3 spec (document_01...): pasted, supersedes Tuesday's draft
Skipped 2 items already in Seaglass.
```

The counts come from the receipts, not from what you set out to store. Keep it
tight: ids and one-line rationales, no ceremony. If anything looked ambiguous
(two people named Ada, an unclear project), say so and ask the user before
writing it.

## What you MUST NOT do

- Don't dump the raw transcript as a single document. Capture distinct
  observations.
- Don't write everything you ever saw. Be selective: the wiki is the product,
  and noise hurts every future read.
