---
name: seaglass-memory-cli
description: Read and write personal memory through the Seaglass `seaglass` CLI. Use when the user references prior conversations ("what do I know about X"), states a fact worth remembering, asks you to store something, or corrects a stored fact. Drives the same Seaglass backend as the MCP plugin but over `bash` for cheaper per-turn token cost.
---

# Seaglass memory (CLI)

You are connected to **Seaglass**, a persistent memory layer that syncs across
the user's AI tools. This skill teaches you to use the `seaglass` CLI for it.

## Setup — install and authenticate

The CLI is the single auth boundary. Two failure modes to handle:

- **`seaglass: command not found`** — CLI isn't installed. Tell the user once:
  `uv tool install ./cli` (or `pipx install ./cli`) from a Seaglass clone.
  Don't retry in a loop.
- **Exit code 5 from any command, or `seaglass whoami` non-zero** — CLI is
  installed but not authenticated. Offer to run `seaglass auth login` for the
  user rather than only describing it: say what it does and ask once, then run
  it on yes — e.g. *"Seaglass isn't authenticated. I can run `seaglass auth
  login` for you — it opens your browser to approve. Want me to?"* Offer first,
  then run on yes: it opens a browser and blocks until the user approves, so
  confirm before firing it. On approval the bearer token is cached at
  `~/.config/seaglass/token`. Every later `seaglass` call (and the MCP shim,
  and Claude Desktop, and Claude Code) picks it up automatically — no env vars
  to copy. For a non-default deployment they should `export
  SEAGLASS_URL=https://...` before logging in.

`seaglass auth login` is the auth flow you should recommend. `SEAGLASS_TOKEN`
exists as a CI / non-interactive fallback (env var wins over the cached file),
but only mention it if the user explicitly asks about scripted or headless
auth — for a human at a terminal, `auth login` is the answer.

To verify the setup is live before doing real work, run **one** of:

```bash
seaglass auth status   # shows where the active token comes from + URL
seaglass whoami        # round-trips an MCP initialize through the token
```

Run at most once per session if you suspect auth is shaky. Don't poll.

## At the start of a session — `seaglass me`

Run this **before any other Seaglass work** in a conversation:

```bash
seaglass me --json
```

Returns the user's profile (preferences, working style) plus their canonical
self page wiki page. Use what comes back to tune your own behaviour for
the rest of the session — communication style, tooling preferences, recurring
projects. If the profile is empty, the user hasn't taught Seaglass much about
themselves yet; treat that as a normal cold-start, not a problem to flag.

In Claude Code, the `SessionStart` hook
([ADR-0007](../../../../../docs/adr/0007-plugin-hooks-for-claude-code.md))
already injects the profile as additional context before your first turn,
so you'll usually see it without running this command. Re-run only if you
want a fresh fetch mid-session.

## When to read

Any time the user references a person, project, topic, or past conversation:

```bash
seaglass search "<query>" --json
```

Inspect the JSON `mode`:

- `page` — read the page from `page.synthesis_markdown`. Use
  `page.slug` for exact follow-up refs or `page.title` when the
  user wants a human label.
- `document` — full content is in `document.content`.
- `memory` — single memory in `memory.content`.
- `resolution_required` — exit code 4. Render
  `suggested_clarification_question` to the user and wait for their answer
  before retrying with the disambiguated `id` from `results`.
- `index` — ranked results. Use the top hit if `suggested_action` is
  `use_top_candidate`; otherwise present options to the user.
- `no_match` — exit code 3. Don't pretend; ask the user.

## When to write

**Check the `Writing` and `Asking` lines from `seaglass me` first — they
gate the triggers below and override them.** Follow them literally even
when a clear, capture-worthy fact is in front of you:

- **`Writing: reserved`** — don't capture proactively; write only when
  the user explicitly asks ("remember that…"). A clear fact alone is not
  a trigger in this mode.
- **`Writing: balanced`** (usual default) — capture clear, durable facts;
  skip the marginal.
- **`Writing: eager`** — capture liberally, including soft asides.
- **`Asking:` confirm-before-writing-about-people** — when set, ask
  before storing a memory about a third party; wait for the yes first.

Within what `Writing` allows, trigger on clear factual statements,
decisions, expressed preferences, corrections, or pasted content the
user wants kept:

```bash
seaglass memory store \
  --page "Sarah Chen" --type people \
  --content "Sarah is leading the Q3 launch on Project Nova." \
  --link-projects "Project Nova" --link-topics "Q3 launch" --json
```

Pass **names**, not IDs, for `--page` unless you've already resolved one.
`--type` is required only when creating a new page. For longer content,
use `seaglass document store --file <path>` or pipe via `--stdin`.

### Link flags — secondary pages mentioned in the memory

| Flag | Category | Example |
|---|---|---|
| `--link-people NAME` | person | `--link-people "Sarah Chen"` |
| `--link-projects NAME` | project | `--link-projects "Project Nova"` |
| `--link-topics NAME` | topic | `--link-topics "Q3 launch"` |

All three are repeatable (`--link-people Sarah --link-people Bob`). Categories
outside this set are silently ignored — there's no `--link-custom` or
`--link-pages`. Each linked page gets a synthesis re-queue, so don't
link pages the memory doesn't actually mention.

## House voice (when authoring pages)

When you author a wiki page directly via `seaglass page edit` /
`page append` / `page create`, follow the same brief Seaglass's
server-side synthesis worker uses — six rules identical to
`synthesis/prompts.py::PAGE_SYNTHESIS_SYSTEM` so the wiki reads
coherently regardless of which writer wrote which page:

1. **Prose, not bullets.** The page should read like an
   encyclopedia entry about someone the user actually knows.
2. **Wrap every cross-link.** `[[Canonical Name]]` for flat pages,
   `[[parent/child]]` for nested sub-pages. Use the canonical form.
3. **Don't invent.** Every claim should trace to a memory, document,
   or fact the user has told you. Cite typed IDs via
   `--evidence memory_… --evidence document_…` — the audit trail
   surfaces them in the wiki UI.
4. **Surface contradictions.** When sources disagree, say so plainly
   instead of picking a side.
5. **End with a "See also" list** of related pages.
6. **Keep the one-line summary tight and indexable.**

## When to author a page directly

Run `seaglass me --json` (or read `seaglass://profile` via MCP) and
check the `## Mode` section. ADR-0005 routes cost two ways:

- **agent mode** — you author pages directly through `seaglass page
  edit` / `page append` / `page create`. The synthesis worker stays
  out of the way; LLM work runs on your subscription.
- **server mode** — capture via `seaglass memory store` and
  `seaglass document store`; the synthesis worker authors and
  updates pages on Seaglass infrastructure.

In agent mode, the flow for a meaningful fact is:

```bash
# 1. Read the current state + version (omitted --base-version below
#    causes `page edit` to fetch it for you automatically).
seaglass search "Sarah Chen" --json

# 2. Edit a single section, citing the captures that justify it.
seaglass page edit "Sarah Chen" \
  --section "Current role" \
  --content "Staff designer at [[Anthropic]]. Started 2026-05-06." \
  --evidence memory_01HX... --evidence document_01HX... \
  --edit-summary "job change"
```

On exit code surfacing `VERSION_CONFLICT` the CLI prints the current
version and excerpt — re-fetch and re-apply. Use `seaglass document
store --no-extract` for raw artifacts you'll author from but don't
want Seaglass extracting on your behalf.

### Explicit page creation

When you want to register a page *without* writing a memory about it:

```bash
seaglass page create --type projects --title "Project Nova" --json
seaglass page create --type people --title "Sarah Chen" --identity-hint "Linear PM" --json
```

`--type` is a library-defined page type (ADR-0024): `people` / `projects` /
`topics` are seeded suggestions, but a library may define its own (e.g.
`books`). Use the exact plural slug — never a singular noun like `person`.

`memory store` and `document store` still create pages as a side effect
of writing about them — this verb is for the case where you only want the
node, not a fact attached to it (e.g. preparing a target for a follow-up
write you'll send later).

Do **not** write small talk, transient task state, or scratch code unless
the user explicitly asks to remember it.

### Memory density — bring the context

Make memories useful weeks later, not bumper stickers. Aim for
**200–2000 characters per memory**: one observation, but with the
surrounding scaffolding — when, where, who else was involved, the
rationale, what makes it notable. Don't strip context to make a tighter
claim. Five rich memories beat fifteen one-liners.

❌ `"Sarah is the PM of Nova."`
✅ `"Sarah Chen was confirmed as PM of Project Nova at the April 15 kickoff. Her prior role was CTO at Acme; the user noted this came up alongside the budget pushback she raised the week before."`

### Capture context — what the conversation knows that the doc doesn't

Both `memory store` and `document store` accept `--capture-context "..."`.
Use it whenever the conversation carries framing the bare content alone
wouldn't: what was being discussed, why the user wants this saved, how it
relates to the rest of the session. Server writes an annotation memory
linked to the new memory/doc and uses it to make extracted memories
richer.

```bash
# A pasted spec — the agent knows what the user said about it
seaglass document store --file ./nova-spec.md \
  --page "Project Nova" --type projects \
  --capture-context "User pasted this right after saying 'this is the v3 spec, supersedes the one we discussed Tuesday'." --json

# A captured fact — the agent has the surrounding theme
seaglass memory store \
  --page "Sarah Chen" --type people \
  --content "Sarah pushed back on the Q3 budget allocation." \
  --capture-context "Came up during a 30-min walk-through of the Nova roadmap; same session as the PM confirmation." --json
```

One or two sentences of context is the sweet spot — not a paragraph.

### Document source dates

`seaglass document store --file <path>` auto-captures the file's modification
time as `--source-modified-at` so extraction knows whether a document is
fresh or stale. Pass `--no-source-mtime` to skip the auto-fill, or
`--source-authored-at` / `--source-modified-at` explicitly for web pages
or transcripts where the file mtime isn't meaningful. These are distinct
from `--event-time` (when the observed fact happened) and from the
server-stamped `created_at` (when Seaglass stored it).

### Post-hoc annotations — `seaglass annotate`

When the user retroactively adds context to something already stored
("remember, that doc was really about X", "the reason that decision
mattered was Y"), use `seaglass annotate <target_id> "<note>" --page "<name>"`:

```bash
seaglass annotate document_01HX... \
  "User clarified that this spec was the one Sarah objected to in the budget discussion." \
  --page "Project Nova" --json
```

The target_id can be a `document_*` or `memory_*`. Annotations participate
in the wiki page synthesis like any other memory.

When you fetch an page, document, or memory back via `seaglass search --json`,
the response includes any attached annotations inline under `annotations:
[{id, content}]` so you can see the framing without a second round-trip.

## Sensitivity

If the user wraps content in `<private>...</private>`, pass it through
verbatim — Seaglass forces `sensitivity: private` server-side regardless of
what flag you set. If the user says "off the record" / "between us" /
"don't remember this", add `--sensitivity private`. For factual but
delicate content (compensation, health), use `--sensitivity sensitive`.

When reading, never pass `--include-private` unless the user explicitly
asked for their private notes. See `reference/sensitivity.md` for the
full matrix.

## Common command shapes

```bash
# Read
seaglass search "<query>" --json
seaglass search "Sarah Chen" --type people --limit 5 --json

# Write a memory
seaglass memory store --page "<name>" --type people --content "<fact>" --json

# Capture a document (file, paste, transcript)
seaglass document store --file ./notes.md --page "<name>" --type projects --json
echo "<paste body>" | seaglass document store --title "Q3 standup" --stdin --page "Q3 launch" --type projects

# Big file? Add --via-upload — POSTs the body via /v1/documents/upload
# instead of through the JSON-RPC tool argument. Same auth + provenance
# behavior; cheaper for large bodies. Requires --file. Re-uploads of the
# same body return {deduplicated: true} with no new extraction work.
seaglass document store --file ./long-transcript.md --via-upload --page "Q3 standup" --type projects --json

# Load the user's profile at session start
seaglass me --json

# Register a page without writing a memory about it
seaglass page create --type projects --title "Project Nova" --json

# Correct a stored fact
seaglass flag memory_01HX... --action flag_incorrect --reason "wrong manager" --json

# Diagnose memory confusion (analysis mode — no resolution)
seaglass reconsolidate "I think you have the wrong Steve" --json
# Apply a resolution after the user confirms
seaglass reconsolidate "split Steve" --kind split --details-json '{...}' --json
```

## Reading the JSON

`seaglass search --json` returns one of:

```json
{"mode": "page",     "page":     {"id": "page_01...", "slug": "people/sarah-chen", "title": "Sarah Chen", "synthesis_markdown": "..."}}
{"mode": "document", "document": {"id": "document_01...", "title": "...", "content": "..."}}
{"mode": "memory",   "memory":   {"id": "memory_01...", "content": "...", "primary_page_id": "page_01..."}}
{"mode": "index",    "results":  [{"id": "memory_01...", "score": 0.84, "preview": "..."}], "suggested_action": "use_top_candidate"}
{"mode": "resolution_required", "results": [...], "suggested_clarification_question": "Did you mean Sarah Chen (Linear PM) or Sarah Chen (the founder)?"}
{"mode": "no_match", "results": []}
```

`seaglass memory store --json` returns:

```json
{"success": true, "memory_id": "memory_01...", "primary_page_id": "page_01...",
 "resolved_refs": [...], "created_pages": [...]}
```

`seaglass flag --json` returns:

```json
{"success": true, "target_id": "memory_01...", "action": "flag_incorrect",
 "sensitivity": "normal", "affected_page_ids": ["page_01..."]}
```

`seaglass reconsolidate` (analysis mode) returns `mode: analysis`,
`diagnosis`, `sub_identities`, `suggested_resolutions`, and a
`suggested_clarification_question` you should ask the user before the
apply call.

## Exit codes — what to do with each

| code | meaning | action |
|---|---|---|
| 0 | success | continue |
| 1 | generic failure | read stderr; don't retry blindly |
| 3 | not found | tell the user honestly; don't fabricate |
| 4 | resolution required (ambiguous page) | ask the user the clarification question shown in stderr / `--json` data |
| 5 | auth failure | tell the user to run `seaglass auth login` (or, if they're on the `SEAGLASS_TOKEN` env-var path, to check the env var); don't retry |

## What you MUST NEVER do

- Do not pass `--user-id`, `--agent-id`, `--session-id`, or any identity
  fields. They don't exist. Auth comes from the token cached by `seaglass
  auth login` (or `SEAGLASS_TOKEN` for CI), never from CLI flags.
- Do not pipe `seaglass search` output back into `seaglass memory store` — you'll
  re-store what you just retrieved.
- Do not pass `--include-private` reflexively. The user opting in to
  private mode is a deliberate act.

## When to escalate to the user

- Conflicting facts or `suggested_action: clarify_with_user` from `search`.
- Exit code 4 (resolution required) — render the clarification question
  shown in the error data.
- Exit code 5 — auth setup question for the user.

See `reference/sensitivity.md` for the `<private>` tag, the three
sensitivity levels, and `--include-private` semantics.
