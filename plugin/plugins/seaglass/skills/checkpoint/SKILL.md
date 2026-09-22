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
- Corrections to prior facts (store the new fact with `supersedes`, or `update_memory` retract; not a plain new write).
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
`store_document`). Three requirements specific to checkpoint mode:

1. **Density.** 200–2000 chars per memory, with the surrounding scaffolding —
   when, who else was involved, the rationale, what makes it notable. Five
   rich memories beat fifteen one-liners.

2. **Capture context.** Every write should include `capture_context` (one
   to two sentences) describing what the conversation knew that the bare
   content alone wouldn't — the framing, the preceding topic, why the user
   surfaced it. The server uses this to make extracted memories richer.

   ```json
   {
     "content": "Ada Example confirmed as PM of Project Example at the April 15 kickoff. Previously CTO at Example Corp; the user noted this came up alongside her budget pushback the week before.",
     "primary_page": "people/ada-example",
     "links": {"projects": ["projects/project-example"], "topics": ["Q3 launch"]},
     "capture_context": "End-of-session checkpoint after a 30-minute review of the Project Example staffing plan; user wanted Ada's role and the Example Corp background preserved together."
   }
   ```

3. **The conversation's own words for when something happened.** A checkpoint
   is written after the fact, so keep the phrasing the conversation used
   rather than resolving it: "last week" stays "last week", "the week before
   the kickoff" stays that, never an anchored calendar date you worked out
   from it. Set `event_time` only from an explicit date or a relative phrase
   naming a specific day against today ("yesterday", "last Tuesday"); a vague
   phrase names no day and sets nothing, and the store time stands in. Where
   the date of the record matters, put it beside the claim ("recorded
   2026-07-23") rather than inside the sentence as part of what was asserted.

## Avoid double-stores

If a memory you're about to write closely matches something already in
Seaglass (you saw it via `search` this session, or you wrote it
earlier this same session), skip it. If the new fact replaces the old one,
store it with `supersedes: [<old_id>]` so the stale row retires in the same
write — or, if it merely adds context, use `store_memory` with
`source_type: annotation` and `source_memory_id` pointing at the original.

## Sensitivity

Respect anything the user said about privacy:

- Inline `<private>...</private>` blocks pass through verbatim — server
  forces `sensitivity: private`. The tags mark the **user's** words: keep them
  around the span the user marked, and never wrap a summary, a
  characterization, or a judgment of your own in them.
- "Off the record", "between us", "don't remember this" → set
  `sensitivity: private` on the write.
- Compensation, health, personal-life details → `sensitivity: sensitive`.

The full matrix lives in the `seaglass-memory` skill's sensitivity
reference doc; load that skill if you need the detailed semantics.

## Report back

After all writes complete, give the user a short summary:

```
Stored 4 memories and 1 document:
  - Ada Example (page_01...) — Project Example PM confirmation + Example Corp background
  - Project Example (page_01...) — April 15 kickoff outcomes
  - Q3 launch (page_01...) — budget pushback context
  - User preference (memory_01...) — async reviews over sync
  - Project Example v3 spec (document_01...) — pasted, supersedes Tuesday's draft
Skipped 2 items already in Seaglass.
```

The summary lists only what each call's `receipt.wrote` says landed. The
counts come from the receipts, not from what you set out to store: a call
that returned an error contributed nothing, and a `receipt` whose `did_not`
is non-empty is relayed in your own words (a deduplicated document was not
newly saved; a store that matched a retired claim did not supersede it).

Keep it tight — IDs and one-line rationales, no ceremony. If anything
looked ambiguous (multiple people named Ada, unclear which project), say
so explicitly and ask the user before writing.

## Examples here are illustrations, never sources

Every name in the examples is fictional and reserved: **Ada Example**, **Bo
Example**, **Project Example**, **Example Corp**. They show the shape of a call,
never a fact.

Never carry a detail from an example into a write, a page, or an answer. If a
detail did not come from this conversation, a tool result, or a document, you do
not have it. When the user gives only a first name, write only that; do not
complete it to a surname you saw here.

This governs where your *content* comes from, not whether to look something up.
The recall rules above are unchanged: a statement that updates or contradicts
something on record still gets a search first.

## What you MUST NOT do

- Don't dump the raw transcript as a single document. Capture distinct
  observations.
- Don't pass identity fields (`user_id`, `agent_id`, `session_id`) — the
  server fills these from auth context.
- Don't write everything you ever saw — be selective. The wiki is the
  product; noise hurts every future read.
