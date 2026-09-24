---
name: recall
description: Load relevant context from Seaglass to prime the current conversation. Use when the user types /recall, asks "what do you know about X", "remind me about that project", "load my notes on Y", or at the start of a session before working on a topic.
disable-model-invocation: true
argument-hint: [optional topic, person, or project]
---

# Seaglass session recall

Read from Seaglass and surface what bears on the current conversation. This skill
adds only what to fetch when the user asks for a recall, and how to lay it out.

## What to fetch

If `$ARGUMENTS` is non-empty, that is the focus: read it.

If `$ARGUMENTS` is empty, work from what the conversation shows:

1. If it has named a person, project, or topic, read each one. Cap it at three
   reads to keep it brisk.
2. If it is brand-new with nothing concrete yet, say who the user is from the
   profile you were given at session start (or the `seaglass://profile`
   resource, if your host can read resources), and offer a one-line "ask me
   about a person, project, or topic".

## How to render

Don't dump whole wiki pages. Summarize each source in two to four bullets, and
cite page names so the user can drill in.

```
**Project Example**: Q3 product launch led by Ada Example (PM) and Bo Example
(eng). Status: design review last week, two-week buffer requested.
Cross-links: Ada Example, Q3 launch, Example Corp migration.

**Ada Example**: Project Example PM (formerly CTO at Example Corp). Recent: pushed back on
Q3 budget allocation, missed the April 8 sync. Async-review preference.
```

Go one level into cross-links, then ask the user where to go next rather than
expanding every link. When a read asks you to choose between pages the name
matched, put the question to the user and stop.
