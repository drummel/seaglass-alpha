---
name: seaglass-cli
description: Drive the user's Seaglass memory with the `seaglass` command-line tool instead of the Seaglass MCP tools. Use when the session context says the `seaglass` CLI is the transport, or when you have a shell but the Seaglass tools are not loaded. It maps each memory operation onto a command; the rules for when to read and write are in the seaglass-memory skill.
---

# The `seaglass` CLI: the same operations over a shell

The `seaglass` binary drives the same Seaglass backend as the MCP tools. It is
the path for this session when the session context says the CLI is the
transport; reach for it too when you have a shell and the MCP tools are not
loaded, when a scripted loop is cheaper than a tool call per item, or when a body
is large enough to want `--via-upload`. The core rules apply unchanged, and each
flag follows the rule written on the tool argument it spells; this skill only
maps those decisions onto commands. It is not a second set of rules.

Every command below takes `--json`; use it, and read the shapes described at
the end.

Contents: [the operation is the command](#on-this-path-the-operation-is-the-command),
[setup and auth](#setup-and-auth), [`seaglass session start`](#orientation-seaglass-session-start),
[read](#read-seaglass-search), [write a memory](#write-a-memory-seaglass-memory-store),
[write a document](#write-a-document-seaglass-document-store),
[annotate](#annotate-seaglass-annotate),
[correct](#correct-seaglass-memory-update-and-seaglass-reconsolidate),
[pages](#pages-seaglass-page-), [feedback](#feedback-about-seaglass-itself),
[the JSON](#reading-the-json), [exit codes](#exit-codes),
[never pass](#what-you-must-never-pass), [never author output](#you-never-author-command-output).

## On this path, the operation is the command

You are on this skill because the shell is the surface. The read and write
operations have MCP tool names (`search`, `store_memory`, `store_document`,
`update_memory`, `reconsolidate_memory`), and on this path those names are not
what you run. The same decisions reach the same backend as `seaglass` command
lines, so express every one of them that way: run the command, or show the user
the exact command line you would run.

**Never narrate a call you cannot make.** Writing the operation's name in prose
-- `**search** (seaglass)`, `seaglass:search`, a `<tool_call>` block -- reads
like work and is not work: nothing runs, no result comes back, and the user is
left with a label instead of an answer. Asked what is known about a topic, the
read is `seaglass search "<topic>" --json`, run or offered. If you cannot run
it, say so and give the user the line to run.

| The decision the skill calls for | The command line it is here |
|---|---|
| Read: recall, "what do we know about X" | `seaglass search "X" --json` |
| Write a fact | `seaglass memory store --library <slug> --page ... --content "..." --json` |
| Write a document | `seaglass document store --library <slug> ... --json` |
| Correct or supersede a fact | `seaglass memory update ... --json` |
| Author or edit a page | `seaglass page create` / `edit` / `append`, each with `--library <slug>` |

The skill decides *whether* an operation is called for and *what* goes in it;
this table only says what it looks like once it is. The rest of this skill
expands each row.

## Setup and auth

The CLI has its own credential, separate from the MCP connector's OAuth grant.
Two failure modes:

- **`seaglass: command not found`**: the CLI is not installed. Do that
  operation over the MCP tools, if they are loaded, and say so once. If the user
  wants the CLI, it installs with `curl -fsSL https://raw.githubusercontent.com/drummel/seaglass-alpha/main/cli/install.sh | bash`
  and then signs in (below); mention that once, when it matters, and do not retry
  in a loop.
- **Exit code 5 from any command, or `seaglass whoami` non-zero**: installed
  but not authenticated. When the Seaglass MCP tools are connected, call
  `cli_handoff` and run the `seaglass auth redeem <code>` command it returns:
  no browser, and nothing for the user to approve. Without the tools, offer to
  run `seaglass auth login` for the user rather than only describing it: say
  what it does and ask once, then run it on yes. It opens a browser and blocks
  until the user approves, so confirm before firing it. Either way the bearer
  token is cached at `~/.config/seaglass/token`, and every later `seaglass`
  call picks it up. For a non-default deployment they
  `export SEAGLASS_URL=https://...` before logging in.

`SEAGLASS_TOKEN` exists as a CI / non-interactive fallback (the env var wins
over the cached file). Mention it only if the user asks about scripted or
headless auth.

```bash
seaglass auth login              # opens a browser; ask the user first, then run on yes
seaglass auth redeem <code>      # no browser: the code comes from the cli_handoff tool
```

To verify the setup is live, run **one** of these, at most once per session:

```bash
seaglass auth status   # where the active token comes from + the URL
seaglass whoami        # round-trips an MCP initialize through the token
```

## Orientation: `seaglass session start`

```bash
seaglass session start --json
```

Starts the session: the user's profile (the same markdown as
`seaglass://profile`), their preferences and custom instructions, and any setup
step, as the `start_session` tool returns them. When the `SessionStart` hook
named the CLI as this session's transport, it already ran this, so re-run it
only for a fresh fetch. `seaglass me` prints the profile alone. Neither is a gate
in front of a read: if the user's first message asks about a person, project or
topic, go straight to `seaglass search`.

## Read: `seaglass search`

This is the read. A question about a named person, project or topic is answered
by running this command and reading its JSON, not by naming `search` in prose
and not from memory.

```bash
seaglass search "<query>" --json
seaglass search "Ada Example" --type people --limit 5 --json
seaglass search "projects/project-example" --json      # typed slug: exact page
seaglass search "<query>" --no-body --json              # skeleton only: outline, no body
```

Inspect the JSON `mode`:

- `page`: read `page.synthesis_markdown`; use `page.slug` for exact follow-up
  refs.
- `document`: full content in `document.content`.
- `memory`: one memory in `memory.content`.
- `index`: ranked results. Use the top hit when `suggested_action` is
  `use_top_candidate`; otherwise present options.
- `resolution_required` (exit code 4): render
  `suggested_clarification_question` to the user and wait for their answer
  before retrying with the disambiguated `id` from `results`.
- `no_match` (exit code 3): say so; do not fabricate.

Fetched pages, documents and memories carry any attached annotations inline
under `annotations: [{id, content}]`.

## Write a memory: `seaglass memory store`

```bash
seaglass memory store --library - \
  --page "Ada Example" --type people \
  --content "Ada is leading the Q3 launch on Project Example." \
  --link-projects "Project Example" --link-topics "Q3 launch" \
  --capture-context "Came up while walking through the Project Example roadmap." \
  --json
```

- `--library` is required on every write: the slug of the library the write
  belongs in, from the map `seaglass me` prints (`-` is the account's default
  library). Pick the library whose collections describe what you are writing;
  a new page is created there, and `--page` is looked up only there.
- `--page` takes a name, a typed slug or a typed id; `--type` is required
  only when creating a new root page, and is the library's plural type slug
  (`people`, `projects`, `topics`, or whatever the library defines).
- The link flags mirror the `links` argument: `--link-people`,
  `--link-projects`, `--link-topics`, each repeatable. Other categories are
  not linkable by flag; name the page inline as `[[Canonical Name]]` in
  `--content` instead, which attaches the same way.
- `--capture-context "..."` is the `capture_context` argument.
- `--supersedes memory_01HX...` is the `supersedes` argument: one write that
  captures the correction and retires what it replaces.
- `--sensitivity private|sensitive` sets the level.
- `--event-phrase "<the user's words>"` is the `event_phrase` argument: when it
  happened, as the user said it ("yesterday", "last week"). The server dates it;
  pass the words, not a date.
- `--event-time <ISO instant>` sets `event_time`, for an exact instant a source
  states. Pass one of the two, never both.

## Write a document: `seaglass document store`

```bash
seaglass document store --library - --file ./notes.md --page "<name>" --type projects --json
echo "<paste body>" | seaglass document store --library - --title "Q3 standup" --stdin --page "Q3 launch" --type projects --json
seaglass document store --library - --file ./long-transcript.md --via-upload --page "Q3 standup" --type projects --json
```

`--via-upload` POSTs the body through the upload endpoint instead of the
JSON-RPC argument: same auth and provenance, cheaper for large bodies, and a
re-upload of the same body returns `{deduplicated: true}` with no new
extraction. `--no-extract` is `extract=false`. `--file` auto-captures the
file's modification time as `--source-modified-at`; pass `--no-source-mtime`
to skip it, or `--source-authored-at` / `--source-modified-at` explicitly for
web pages and transcripts where the mtime means nothing.

## Annotate: `seaglass annotate`

```bash
seaglass annotate document_01HX... \
  "User clarified that this spec was the one Ada objected to in the budget discussion." \
  --library - --page "Project Example" --json
```

Attaches post-hoc context to an existing `document_*` or `memory_*`; the
annotation participates in synthesis like any other memory.

## Correct: `seaglass memory update` and `seaglass reconsolidate`

```bash
# Retract a fact that was never true (no replacement; the note is the tombstone label)
seaglass memory update memory_01HX... --action retract --note "wrong manager, user-confirmed" --json

# Diagnose memory confusion (analysis mode, no resolution)
seaglass reconsolidate "I think you have the wrong Steve" --json
# Apply a resolution after the user confirms
seaglass reconsolidate "split Steve" --kind split --details-json '{...}' --json
```

The other `--action` values are `supersede` (with `--successor`),
`flag_sensitive`, `flag_private` and `redact`. A newer fact is one
`memory store --supersedes`, never retract-then-store, exactly as with the
`supersedes` argument.

## Pages: `seaglass page ...`

```bash
# Register a page without writing a memory about it
seaglass page create --library - --type projects --title "Project Example" --json
seaglass page create --library - --type people --title "Ada Example" --identity-hint "Linear PM" --json

# Author or revise one section, citing the captures that justify it.
# Omit --base-version and `page edit` fetches the current version for you.
seaglass page edit "Ada Example" --library - \
  --section "Current role" \
  --content "Staff designer at [[Anthropic]]. Started 2026-05-06." \
  --evidence memory_01HX... --evidence document_01HX... \
  --edit-summary "job change" --json

seaglass page append "Ada Example" --library - --section "Working style" --content "..." --json
seaglass page history "Ada Example" --json
seaglass page revert "Ada Example" --library - --to-version 3 --json
seaglass page move "projects/seaglass" "projects/atlas" --library - --json
```

`--evidence` is repeatable and is the `evidence_memory_ids` /
`evidence_document_ids` pair. A `VERSION_CONFLICT` prints the current version
and excerpt: re-read and re-apply. `page edit` and friends follow the same mode
rule as the page tools: in server mode the worker authors, and you capture with
`memory store` and `document store`.

## Feedback about Seaglass itself

```bash
seaglass send-product-feedback --kind bug --body "The search result had no outline block." --json
```

The transcript-recall and source-connector operations have no CLI command by
design; they are MCP-only.

## Reading the JSON

`seaglass search --json` returns one of:

```json
{"mode": "page",     "page":     {"id": "page_01...", "slug": "people/ada-example", "title": "Ada Example", "synthesis_markdown": "..."}}
{"mode": "document", "document": {"id": "document_01...", "title": "...", "content": "..."}}
{"mode": "memory",   "memory":   {"id": "memory_01...", "content": "...", "primary_page_id": "page_01..."}}
{"mode": "index",    "results":  [{"id": "memory_01...", "score": 0.84, "preview": "..."}], "suggested_action": "use_top_candidate"}
{"mode": "resolution_required", "results": [...], "suggested_clarification_question": "Did you mean Ada Example (Linear PM) or Ada Example (the founder)?"}
{"mode": "no_match", "results": []}
```

`seaglass memory store --json` returns:

```json
{"success": true, "memory_id": "memory_01...", "primary_page_id": "page_01...",
 "resolved_refs": [...], "created_pages": [...], "receipt": {...}}
```

A non-zero exit from `memory store` / `document store`, or a response without
`success: true`, means the fact is NOT in Seaglass, and you report it the way
the core rules say to report a write that did not land. Every state-changing
response carries the same `receipt` the tools return.

`seaglass reconsolidate` in analysis mode returns `mode: analysis`,
`diagnosis`, `sub_identities`, `suggested_resolutions` and a
`suggested_clarification_question` to ask the user before the apply call.

## Exit codes

| code | meaning | action |
|---|---|---|
| 0 | success | continue |
| 1 | generic failure | read stderr; do not retry blindly |
| 3 | not found | tell the user honestly; do not fabricate |
| 4 | resolution required (ambiguous page) | ask the user the clarification question shown in stderr / `--json` data |
| 5 | auth failure | `cli_handoff` when the MCP tools are connected, else offer `seaglass auth login`; do not retry |

A denial with no exit code ("Denied by user", "The user doesn't want to
proceed with this tool use") is the host's permission layer: the command never
ran. Ask the user to approve, then rerun it unchanged.

## What you MUST NEVER pass

- `--user-id`, `--agent-id`, `--session-id`, or any identity flag. They do not
  exist; auth comes from the cached token (or `SEAGLASS_TOKEN` in CI), never
  from a flag.
- `--include-private` reflexively. Pass it only when the user explicitly asks
  for their private notes, exactly as with `include_private` on the tool.
- `seaglass search` output piped back into `seaglass memory store`: you would
  re-store what you just retrieved.

## You never author command output

A command has run only when you ran it and received its output. If you cannot
run commands here, propose the command and stop; let the user run it and paste
the result back. Never write out a result you did not receive, not as an
illustration and not in a transcript-shaped block.
