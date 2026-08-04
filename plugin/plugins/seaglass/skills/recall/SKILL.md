---
name: recall
description: Load relevant context from Seaglass to prime the current conversation. Use when the user types /recall, asks "what do you know about X", "remind me about that project", "load my notes on Y", or at the start of a session before working on a topic.
disable-model-invocation: true
argument-hint: [optional topic, person, or project]
---

# Seaglass session recall

Read from Seaglass and surface the relevant context for the current
conversation. This is the explicit alternative to a `SessionStart` hook —
useful in Cowork and any other client that doesn't auto-fire plugin
hooks.

## What to fetch

If `$ARGUMENTS` is non-empty, that's the focus topic. Call `search`
with the free-text query.

If `$ARGUMENTS` is empty, infer from what's visible in the current
conversation:

1. Read `seaglass://profile` first — that anchors who the user is and your
   per-agent profile.
2. If the conversation has named a person, project, or topic, query
   `search` for each. Cap at 3 queries to keep it brisk.
3. If the conversation is brand-new with nothing concrete yet, just return
   the profile summary and a one-line "ask me about a person, project, or
   topic" prompt.

## How to render

Don't dump entire wiki pages. Summarize each context source in 2–4
bullets. Cite page names so the user can drill in.

```
**Project Example** — Q3 product launch led by Ada Example (PM) and Bo Example
(eng). Status: design review last week, two-week buffer requested.
Cross-links: Ada Example, Q3 launch, Example Corp migration.

**Ada Example** — Project Example PM (formerly CTO at Example Corp). Recent: pushed back on
Q3 budget allocation, missed the April 8 sync. Async-review preference.
```

If a result is `proceed_with_low_confidence`, use epistemic humility —
"I vaguely recall…" rather than stating as fact.

If a result is `clarify_with_user`, render the
`suggested_clarification_question` and stop. Don't guess.

## Sensitivity

Default to `include_private: false`. Only pass `include_private: true`
when the user has explicitly asked for their private notes ("show me my
private notes on Tom"). The user opting in to private mode is a
deliberate act.

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

- Don't summarize private content into the conversation. The server
  excludes it; respect that.
- Don't expand every cross-link recursively. One level deep, then ask the
  user where to go next.
- Don't pretend on `no_match`. Say so honestly.
