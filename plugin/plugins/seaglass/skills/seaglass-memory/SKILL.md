---
name: seaglass-memory
description: Read and write the user's persistent memory, carried across every AI tool they use. Use when the user references a person, project, topic, or past decision ("what do we know about X", "remind me where that landed"), states a durable fact, decision, preference, or correction worth keeping, asks you to remember or save something, or corrects something already stored.
---

# Seaglass memory skill

You are connected to Seaglass, a persistent memory layer that syncs across the
user's AI tools. Read what Seaglass already knows before assuming; write new
facts when you learn them.

If this client has a memory of its own, Seaglass sits alongside it, not above
it. Durable facts about people, projects, and decisions go to Seaglass so they
reach the user's other tools; this client's own memory is for how to work with
this user here. Use both.

The two sections that follow are when to read and when to write, because that
is the decision you make most often. If the Seaglass tools are missing, a call
comes back unauthenticated, or the host denies a call, skip to the two recovery
sections below them.

## When to read (`search`)

Any time the user references:

- A person by name ("Ada", "my manager")
- A project, tool, or initiative ("the launch", "Project Example")
- A topic that might have context ("the reverse ETL thing")
- Past conversation ("like we talked about last week")

Approach:

1. Call `search` with the free-text query.
2. If `suggested_action` is `use_top_candidate`, use the returned content.
3. If `suggested_action` is `clarify_with_user`, render the
   `suggested_clarification_question` to the user, wait, then re-call. **Prefer
   the `id` from the returned candidates** when you re-call — it's exact and
   skips a second name resolution; fall back to the disambiguated name only if
   you have no id.
4. If `suggested_action` is `proceed_with_low_confidence`, introduce what
   Seaglass returned as tentative — "I vaguely recall you working with Ada
   on reverse ETL; does that sound right?"
5. If `suggested_action` is `no_match`, don't pretend. Ask the user.

**You start already oriented.** The profile you load at session start ends with a
**Your memory at a glance** map: every library you can reach (with read/write and
purpose) and, inside each, every collection (page type) *including empty ones*
with a sample of top-level pages. Use it to pick the right `library` and the
right collection type on the first write, without guessing or probing. The same
map is available on demand as the `seaglass://libraries` resource (JSON, with
each collection's purpose and page count).

**Reads are not library-scoped by default.** `search` spans **every library you
can read** unless you pass `library`. When the user keeps separate contexts —
one library per client, a private library, a shared team library — and the
question is about *one* of them, pass `library: "<name>"` (same name/slug/id you'd
use on a write) to scope the read to that library. Omit it for a normal
cross-context recall. A `library` you can't read (or that doesn't exist) is a
clear error; a real but empty library returns `no_match` with a `library_scope`
marker (its `page_count` and `can_write`), so you can tell empty from missing
without a write-probe. (Note: `scope_hints` is for **time** bounds only —
`after`/`before`; to scope by library use `library` above, not `scope_hints` —
any other `scope_hints` key is now rejected as an error, not silently ignored.)

### Outline-first reads

On an page hit, `search` returns an `outline` block alongside the body —
parent, subpages, cross-links, and see-also pages, each with a one-line
summary. Use it to navigate without speculative follow-up reads:

Set `body` to signal whether you want **structure** or **substance** — they
are different requests:

- **Structure / navigation** → pass **`body=false`**. When you only need the
  shape — parent, subpages, cross-links, see-also — and not the prose (e.g.
  "what's the shape of X", "what sub-pages does X have", or sizing a page up
  before you edit it), call `search` with `body=false` explicitly. Skeleton-only
  mode, much cheaper context.
- **Substance / catch-up** → keep **`body=true`** and add
  `include=["recent_edits"]`. When the user wants to be brought *up to speed* —
  "catch me up on X", "what's the latest", "get me current before my standup" —
  they want the actual content and what changed, **not** the skeleton; read the
  body and surface recent edits.
- For deeper context generally — who links here, when was this last touched —
  pass `include=["backlinks", "recent_edits"]`. The default response is
  intentionally small; opt in when you need it.

**Time-scoped recall** (`scope_hints`): for "what happened last week?",
"what did I work on in April?", "catch me up since Monday", compute the
ISO-8601 bounds from the **current date given to you at session start**
("Today's date is ...") and pass `scope_hints: {after, before}`. Do not
guess the date from memory: a window anchored to the wrong year silently
returns nothing. If you were not given the current date, ask the user for
the window rather than inventing one. With a normal query the window narrows
the results; with `query: "*"` you get **timeline mode** — a digest of
the pages with activity in the window (counts + last-mentioned times),
newest first. Synthesize the narrative from that digest yourself. The
response echoes the applied `time_window`. Only `after`/`before` are accepted: a
malformed instant is dropped (see `dropped_hints`), never an error, but an
unknown key is rejected outright.

> The read tool is `search` (it was once called `get_context`; that name
> has been removed — use `search`).

### Tracing back through past sessions (`transcript_search` / `transcript_read`)

`search` recalls *synthesized knowledge* — what Seaglass distilled from your
sessions. When the user wants the **literal record** of an earlier session
instead — "what was that exact error?", "what did the tool actually return?",
"pull up what we tried before the fix" — and detail has been lost to context
compaction, reach for the transcript tools (only when transcript capture is on
for the deployment):

1. `transcript_search` with a substring (case-insensitive) → line-anchored
   snippets across your own archived session transcripts. Optionally scope to
   one `session_id`.
2. `transcript_read` with a `session_id` (and optional `line_offset`/`line_limit`)
   → the surrounding lines around a hit.

These are a slow, explicit path for trace-back, **not** a substitute for
`search` on normal "what do we know about X" questions. They only ever resolve
*your own* session transcripts.

### Importing from connected sources

The user connects external sources (Google Drive, etc.) and picks which of
their documents Seaglass may see **on the web** — you never connect a source or
browse a whole drive. You import from that human-curated shelf:
`list_source_connections` (which sources are connected) → `list_available_documents`
(what the user made available on one) → `import_source_document` to pull a chosen
document into Seaglass, attaching it to a page via `primary_page`. Use
`resync_source_document` to re-pull one whose source has since changed. Don't
import speculatively — only when the user points at a document they want kept.

## When to write (`store_memory` or `store_document`)

**Check the `Writing` and `Asking` instructions in `seaglass://profile`
first — they gate every trigger below and override it.** They are not
hints; follow them literally even when a clear, capture-worthy fact is
sitting right in front of you:

- **`Writing: reserved`** — do NOT capture proactively. Write only when
  the user explicitly asks ("remember that…", "save this"). A clear fact
  on its own is *not* a trigger in this mode, and a user *stating* a fact
  is not the same as *asking* you to save it — sharing something is not a
  save request. Acknowledge it in conversation and move on without
  writing.
- **`Writing: balanced`** (the usual default) — capture clear, durable
  facts as they come up; skip the marginal.
- **`Writing: eager`** — capture liberally, including soft preferences
  and offhand asides.
- **`Asking:` confirm-before-writing-about-people** (or similar wording)
  — when the instruction says to ask first, do NOT write a memory about a
  third party until the user approves. Ask, wait for the yes, then write.

Within whatever the `Writing` instruction allows, capture in the same turn the
user says it. Nothing files it later: no background pass sweeps the conversation,
so a fact left uncaptured is gone when it ends. Trigger on:

- Clear factual statements about a person, project, or topic.
- Decisions the user makes.
- Preferences expressed ("I prefer async reviews").
- Corrections to prior statements.
- Files, pasted content, or URLs worth keeping.

**Recall first when the fact changes something already on record.** Most captures are new
information and go straight to `store_memory`. Look first only when the statement *updates
or contradicts* something you already know: a title that changed, a decision reversed, a
status that moved. Those writes have to replace the old claim rather than sit beside it.

- The new fact refines what is stored: capture the nuance, don't restate the whole thing.
- The new fact *contradicts* what is stored: that is a correction, not a second opinion.
  Declare it with `supersedes: [<old_id>]` so the old claim is retired instead of left to
  argue with the new one.
- Once recall comes back empty, write. A narrower follow-up read or two is fine when it
  might surface a cross-link candidate, but the empty result stands: don't wait on more
  searches before capturing. When recall *hits*, write to the page it returned instead of
  searching again.

Two things this does *not* mean:

- **A plainly new fact needs no lookup.** "Priya just joined as our data lead" is new
  information. Write it.
- **An empty search is an answer, not a blocker.** If you do look and find nothing, that
  settles it: capture the fact as new. Never turn a miss into an interrogation. Don't ask
  the user which Ada they meant just because no page exists yet.

Either way, name the target: pass `primary_page` on every `store_memory`, the resolved slug
when you have one, the subject's name when you don't.

You are not on your own here. Every `store_memory` response carries `related_context`, the
pages nearest what you just wrote (excluding the one you wrote to). That is the safety net
for the writes you didn't look up first: if it surfaces something you should have written
differently, fix it on the next turn, append to the right page, or supersede the claim you
contradicted.

**A failed write is reported, never papered over.** If `store_memory` or `store_document`
returns an error, the fact is NOT in Seaglass, and the user must not walk away believing
it is: they will drop it from their own working memory and it is gone. One quiet retry is
fine when the error looks transient. After that, say plainly that the capture did not
happen and why. Never describe a failed or unattempted write as saved.

Do not write:

- Small talk, greetings, conversational filler.
- Transient task state ("I'm on step 3 of 7").
- Ephemeral code or scratch work unless the user asks to remember it.

**The `Asking` gate is evaluated last and overrides every trigger above.**
When `Asking` says to confirm before writing about other people, a clear
factual statement about a third party is a cue to *ask*, not to write,
that clarity is exactly what the gate is for, not an exception to it. Name
what you'd record, wait for an explicit yes, then call `store_memory`.

**`event_time` is for a date you can ground, not a guess.** The rule travels
with the field, on the `event_time` argument itself: an explicit date, or a
relative phrase naming a specific day against today ("yesterday", "last
Tuesday"), sets it. A vague phrase ("last week", "recently", "end of Q3") names
no day and sets nothing, and a standing fact reported with no time at all sets
nothing either. Omit it in both cases, the store time stands in. Most captures
have no `event_time`, and that is the normal outcome: a wrong one misdates the
memory forever.


## At session start

Read `seaglass://profile`. It returns markdown with four sections:

1. **About you** — the synthesized identity Seaglass has built about the user,
   plus an overlay describing how *this* integration has seen them.
2. **How to behave** — four hand-crafted instruction sentences (Reading,
   Writing, Asking, Voicing) derived from the user's effective preferences.
   Follow them literally; they replace any general behavior assumption.
3. **Custom instructions** — the user's free-form notes (limits, defaults,
   tone). User-level first, with integration-specific additions appended.
4. **Adjusting how I behave** — links the user can visit (and CLI commands
   they can run) to change preferences. Share these verbatim when asked.

In Claude Code, the `SessionStart` hook
injects the profile markdown as `additionalContext` before your first turn,
so you'll already see it — don't re-fetch unless you need a refresh mid-session.
In clients that don't run plugin hooks (Cowork, some IDE extensions), the user
can invoke `/recall` to prime the conversation manually. See the
**Explicit checkpoint and recall** section below.

## If the Seaglass MCP tools aren't available (or a call comes back unauthenticated)

You're reading this skill because the `seaglass-memory` plugin is installed,
but if the actual MCP tools (`search`, `store_memory`, `store_document`,
`update_memory`, `reconsolidate_memory`) aren't loaded — or a tool call returns
an unauthenticated / not-connected error — the MCP server hasn't connected.
The cause is almost always auth, and the fix is one command: `seaglass auth
login`.

**Offer to run it for the user — don't just describe it.** In a client where
you can run shell commands (Claude Code), say what you're about to do and ask
once, then run it on yes. For example:

> Seaglass isn't connected yet. I can run `seaglass auth login` for you — it'll
> open your browser to approve the connection. Want me to?

On yes, run `seaglass auth login`. It opens the Seaglass web app, the user
clicks **Approve**, and a bearer token is cached at `~/.config/seaglass/token`;
the `seaglass bridge` stdio transport the plugin invokes picks it up
automatically.

Handling notes:

- **Name the exact command in your reply.** Say `seaglass auth login`
  verbatim (as above), not "the login command" — the user may act on your
  message later, from a terminal you can't see.
- **A connection problem is not product feedback.** Do not call
  `send_seaglass_product_feedback` (or any other Seaglass tool) about the
  tools being unavailable; reply in text with the offer and the command.
- **Offer first, then run on yes.** `auth login` opens a browser and blocks
  until the user approves — it's a deliberate, outward-facing step, so confirm
  before running it rather than firing it unprompted.
- **Non-default deployment:** have the user `export SEAGLASS_URL=https://...`
  before `auth login` (set it in the same command/shell), then run the login.
- **After approval**, the client (Claude Code / Desktop / Cowork) needs to
  restart the session for the MCP server to reconnect and the tools to load.
- **No shell available?** In a client where you can't run commands (Desktop /
  Cowork), you can't run it yourself — tell the user to run `seaglass auth
  login` in a terminal, or point them at the Connect page in the Seaglass web
  app to authorize from the browser.

`seaglass auth login` also covers the `seaglass` CLI plugin variant — same
cached token, same auth boundary.

If MCP tools _are_ available, ignore this section.

## A permission denial is the host, not Seaglass

"Denied by user", "The user doesn't want to proceed with this tool use", or
"[Request interrupted by user for tool use]" is the host's permission layer:
the call never reached Seaglass. Tell the user, ask them to approve (or allow
the Seaglass tools, e.g. `/permissions` in Claude Code), then retry the
identical call. Don't change arguments, switch modes, abandon the task, or
file product feedback over it. A real Seaglass failure is a structured error
with a `code` and `message` (plus `agent_next_steps` on `error.data`) or an
HTTP transport failure.

## House voice (when authoring pages)

When you create or edit a wiki page directly via `edit_page`,
`edit_section`, `append_section`, or `create_page`, follow the same
brief Seaglass's server-side synthesis worker follows. Seven rules,
identical to `synthesis/prompts/page.py::PAGE_SYNTHESIS_SYSTEM` so the
wiki reads coherently regardless of which writer wrote which page:

1. **Prose, not bullets.** The page should read like an encyclopedia
   entry about someone the user actually knows.
2. **Wrap every cross-link.** `[[Canonical Name]]` for a flat page,
   `[[parent/child]]` for a nested sub-page. Use the canonical form,
   not a partial: `[[Ada Example]]`, not `[[Ada]]`.
3. **Don't invent.** Every claim should trace to a memory, document,
   or fact the user has told you directly. When you cite, pass the
   typed IDs as `evidence_memory_ids` / `evidence_document_ids`,
   surfaced in the audit trail.
4. **Surface contradictions.** If sources disagree, say so plainly
   ("Two notes disagree about X: one says A, another says B")
   rather than picking a side.
5. **End with a "See also" list** of related pages worth
   exploring next: co-mentioned people, parent topics, recent
   projects. Only pages that genuinely relate, drawn from your
   sources or the pages you actually found. When nothing does,
   omit the section: an empty See also beats an invented one, and
   an example slug from these instructions is never a real entry.
6. **Keep the one-line summary tight and indexable.** It shows up in
   outlines, search results, and the parent page's subpages list.
7. **No em dashes.** Use a comma, colon, or period instead. The long
   dash character never belongs in a page body, one-line summary, or
   edit summary you author.
8. **Keep the source's own words for when something happened.** If the
   user said "last week" or "end of Q3", write that, never an anchored
   calendar date you worked out from it. A body sentence reads as a
   recorded claim, so a day nobody stated is a fact you invented. Where
   the date of the record matters, attribute it to the record beside the
   claim ("recorded 2026-07-23"), not inside the sentence as part of
   what was asserted.

## When to author a page directly

Check `seaglass://profile`'s `## Mode` section first. The user has
chosen one of two cost-routing modes:

- **agent mode** — author pages directly via `edit_page` /
  `edit_section` / `append_section` (and `create_page` for new ones).
  Server-side synthesis is suspended; the LLM work runs on your
  subscription. This is the agent-mode write path. **Because the worker
  is off, a `store_memory` about a subject that already has a page is
  orphaned — nothing folds it in. So when the page exists, AUTHOR the
  new fact onto it** (`append_section` for a dimension it has no section
  for; `edit_section` / `edit_page` to revise existing content);
  reserve `store_memory` for when there's no page yet.
- **server mode** — capture observations via `store_memory` /
  `store_document`; the synthesis worker authors and updates pages
  on Seaglass infrastructure. Page-edit tools are still available
  for explicit corrections.

In agent mode, the flow for a meaningful fact is:

1. `search` the page to read the current page body **and** version.
2. Compose the new content (whole page or just one `## Section`).
3. Call `edit_page` (or `edit_section` / `append_section`) with
   `base_version` from the read. On `VERSION_CONFLICT`, re-read and
   re-apply.
4. Cite evidence via `evidence_memory_ids` /
   `evidence_document_ids` so the audit history shows what you
   based the edit on.

For evidence that isn't itself a page edit, pick by shape:

- **Atomic observation with no home page yet** → `store_memory`.
- **A raw artifact you were handed** — a pasted document, transcript,
  email, meeting notes, a log — → `store_document`. When the user says
  **"keep this"**, **"for reference"**, **"file this"**, or **"save these
  notes"**, they are handing you an artifact to store **whole and verbatim**
  — even when it is full of distinct decisions and action items. Do **not**
  "capture the key points" by paraphrasing it into a handful of
  `store_memory` calls. In agent mode *you* mine those facts later when you
  author the pages (citing the doc via `evidence_document_ids`); splitting
  the artifact into memories up front scatters it and loses the source.

Leave **`extract` unset** on `store_document` and the server picks the
default for your mode: agent mode keeps the document verbatim for you to
mine at author time, server mode extracts it into memories now. Pass it
only to **override** that default — `extract=false` forces verbatim even in
server mode (the raw-artifact cases above), `extract=true` forces extraction
now even in agent mode. You rarely need either.

### Write what the sources support

Authoring is the job; supplying the specifics nobody gave you is not. Everything
on a page traces to something: the user said it, a tool returned it, or a cited
document contains it.

- Don't fill a heading because the template has one. Thin sources read thin.
- Don't explain a mechanism you weren't told. "Redis is the source of truth" is
  the fact; how it is wired is not.
- Don't attribute a role, an owner, or a rationale nobody stated.
- Don't write date arithmetic as a date of record. "Shipped last week" stays
  "last week", or "the week of 2026-07-20".

Mark inference as inference ("this suggests", "worth confirming"). An unhedged
guess is a fabrication with good posture.

## How to call the write tools

### Three forms of page reference

* **Typed slug** — `projects/seaglass/competitors`, `people/ada-example`.
  Always slash-separated, lowercase kebab-case, first segment is the page
  type. Types are **library-defined** and plural by convention
  (`people` / `projects` / `topics`, plus whatever the library adds); they
  are not a fixed global set. The most precise form; it identifies an exact
  page. **A nested slug requires its parent slug to already exist** —
  Seaglass never auto-creates ancestors.
* **Typed id** — `page_01HX...`. Use when you've already resolved a page
  and want to pin to that specific row.
* **Bare title** — `"Ada Example"`. Free-text; resolves by title +
  aliases. May surface `resolution_required` if multiple pages share
  the title (cross-type collisions are first-class — `projects/anthropic`
  and `topics/anthropic` can coexist). When you're creating a NEW page
  from a bare title, pass `primary_page_type` (a type the library defines,
  e.g. `people` / `projects` / `topics`) so Seaglass knows which root to make.

**Picking the `create_page` shape:**

* **New top-level page** → pass **`type` + `title`** (e.g. `type: "projects"`,
  `title: "Project Helios"`). Use the library's plural type slug, never a
  singular noun like `project`.
* **Nested sub-page** → pass the **full typed `slug`** (e.g.
  `projects/seaglass/pricing/enterprise`), not `parent` + `title`. The parent
  slug must already exist — Seaglass never auto-creates ancestors.

If a tool response includes `resolution_required` (JSON-RPC error code
-32010), do NOT assume — render the `suggested_clarification_question` to
the user and wait for their answer.

### `links` parameter

When a memory mentions multiple pages, populate `links` with the
secondary pages (people the user is not primarily describing, projects
peripherally involved, etc.). This is what lets the wiki cross-link densely.

`links` does more than draw an edge. Every page you list is re-synthesized
on this memory's account **and reads the memory as evidence**, so it can
state the fact and cite it in its source trail. Declare the pages the
observation genuinely supports; a name it only mentions in passing is a
page that will now quote it.

Example:

```json
{
  "content": "Ada is leading the Q3 launch on Project Example.",
  "primary_page": "people/ada-example",
  "source_type": "primary",
  "source_origin": {"kind": "conversation"},
  "links": {
    "projects": ["projects/project-example"],
    "topics": ["Q3 launch"]
  }
}
```

Mixing slug refs and bare titles in `links` is fine — slugs are exact and
free-text falls back to title resolution.

**Or name the page inline.** A `[[Canonical Name]]` or `[[type/slug]]`
written into `content` attaches the same way, which is the natural form
when the page is part of the sentence:

```json
{
  "content": "Ada moved the launch to October after the [[Project Example]] review.",
  "primary_page": "people/ada-example",
  "source_type": "primary",
  "source_origin": {"kind": "conversation"}
}
```

Only links that resolve attach; an ambiguous or unknown name stays literal
text and binds nothing. Use whichever form fits: `links` when you are
listing pages, `[[...]]` when you are writing a sentence.

**Never search to fill these in.** Write the name the user used and let the
server resolve it: that is what resolution is for, an unresolved name costs
nothing (it stays literal), and a wrong guess is corrected by the related
pages the write hands back. Linking is a thing you do *while* capturing, not
a reason to go look something up first.

**Bracketing a name is not a licence to rewrite the observation.** Put the
brackets around a name the sentence already contains and leave every other
word alone. This matters most for `<private>...</private>`: Seaglass forces
`sensitivity: private` by finding those tags in `content`, so an observation
you paraphrased while adding a link can arrive with the tags gone and the
server's guarantee with them. If a name you want to link sits inside a
private span, leave the span exactly as the user wrote it and use `links`
instead.

### `library` parameter (where a write lands)

`store_memory`, `store_document`, and `create_page` take an optional
`library` — the name, slug, or id of the library to write into. **Omit it**
and the write lands in your agent's home library (the account's default
library `-` as a fallback); that is the right choice almost always, and it
keeps the solo experience identical to before.

Pass `library` only when the user keeps separate contexts and asks you to
record into one — e.g. `library: "work"` for a named library, or
`library: "-{your-handle}"` for your own private library (it's
**materialized on first write**, so you never have to create it). Read
`seaglass://libraries` to see which libraries you can write to and their
slugs. You must have write access to the target, or the call is rejected.

### Outcome receipts (`receipt`)

Every state-changing response carries a `receipt`: `{action, wrote, did_not,
statement}`, composed by the server from what the call actually did. When you
tell the user what happened, say what `receipt.statement` says and nothing
more. `wrote` is the complete list of what landed; do not add to it. When
`did_not` is non-empty, relay it in your own words wherever the user would
otherwise assume it happened: a store that matched a retired claim performed
no supersession, so say the old claim still stands unless you supersede it. A
response with no receipt is an error, not a success; report it as a failure.

## Server next-step hints (`agent_next_steps`)

Some tool responses carry an `agent_next_steps` array: directives the
server computed for **you**, the calling agent, from what the call just
did. The same array rides `error.data` when a call fails. They are
advisory, but usually name real follow-up work you are the only one
positioned to do.

Each item has a stable `code` you branch on, a second-person `message`
telling you what to do, and structured `refs` (page ids, names) so you
never parse targets out of the prose. Read the `code` and `refs`, not the
sentence. Common ones: author a page you now owe synthesis for, re-author
pages after a change re-queued them, ask the user to disambiguate a
reference that matched more than one page, fix cross-links that didn't
resolve, or re-apply an edit against the current version after a conflict.

## Sensitivity handling

When the user wraps content in `<private>...</private>`, pass it through
as-is in the `content` field. Seaglass will honor the tag and store at
`sensitivity: private` regardless of the `sensitivity` parameter you pass.

When the user says phrases like:

- "don't remember this", "off the record", "between us", "keep this private"

Set `sensitivity: private` on the write.

When reading, never echo or summarize private content back into another
client's context. The server already excludes it from `search` unless
you explicitly pass `include_private: true` — only do that when the user
explicitly requests their private notes.

See `reference/sensitivity.md` for detailed behavior of the `<private>` tag,
sensitivity levels, and when to pass `include_private: true`.

## Renaming and moving pages (`move_page`)

When the user wants a page at a different **address** — "rename the
seaglass project to atlas", "make competitors a sub-page of
projects/seaglass", "free up that name, we're starting over" — call
`move_page` with the page and the full new typed slug in `to`
(e.g. `to: "projects/atlas"`). Rules:

- `to` is always the **full typed slug**, never a bare leaf. The type
  segment (first segment) cannot change — a `projects/...` page stays
  `projects/...`.
- Sub-pages move with their parent automatically; don't move them
  one by one.
- The page ID never changes, and the old address keeps redirecting
  until a new page occupies it — so do NOT rush to rewrite
  `[[old/slug]]` links elsewhere; they still resolve, and synthesis
  heals the literals over time.
- A rename is an address change, not a content edit: don't use
  `edit_page` to retitle a heading when the user means "rename the
  page".
- Pass `title` to update the display name in the same call (the old
  title is kept as an alias and stays findable). For a title-only
  rename, pass `title` with `to` equal to the current slug.

**Boundary:** `move_page` is *address* surgery. If the problem is
*identity* — memories that belong on a different page, two people
mixed together, a page that should be split or merged — that is
`reconsolidate_memory` (next section), never `move_page`.

## Reconsolidation

If the user indicates memory confusion:

- "Wait, are you mixing up two different Steves?"
- "I think you have the wrong person."
- "Let's split those two things — they're different."

Call `reconsolidate_memory` with a description of the problem (analysis
mode — no `resolution` argument). The server returns a diagnosis and a
`suggested_clarification_question`. Ask the user with that question. Once
they confirm, call `reconsolidate_memory` again with the `resolution`
object filled in (apply mode).

One thing the recall-first rule does *not* mean:

- **This is a capture rule, not a preamble for everything.** Structural and corrective
  tools (`move_page`, `reconsolidate_memory`, `edit_section`, `revert_page`) already take
  an explicit target. Don't front them with a lookup you don't need.

## What you MUST NEVER pass

Never include `user_id`, `agent_id`, `session_id`, `seaglass_session_id`,
`client_session_id`, or any identity-bearing fields in tool inputs. The
Seaglass server fills these from authenticated session context.

## Low-confidence reads

If `search` returns a result with `suggested_action: proceed_with_low_confidence`,
frame the reply with epistemic humility: "I vaguely recall..." rather than
stating as fact.

## Adjusting how you behave

If the user asks you to change how you read, write, ask, or narrate
(e.g. "stop being so chatty," "ask before writing about people,"
"capture more aggressively"), respond like this:

> "I can adjust my behavior for this session if you'd like. To make changes
> stick across sessions, you can edit your defaults at <user_profile_url>
> (CLI: `seaglass profile`). To make changes just for me in this integration,
> use <agent_profile_url> (CLI: `seaglass profile agent <agent_id>`)."

Both URLs and CLI hints arrive in the `## Adjusting how I behave` section of
the profile you were already given: at session start, and again on the
preferences block that rides your first tool call. Render them verbatim from
what you have. **Don't go looking for them.** There is no tool that fetches a
resource, so searching for `seaglass://profile` finds nothing; it only queries
the user's memories for a URI. If you genuinely don't have the section, say the
settings live in the Seaglass web app rather than inventing a URL.

When the user says "yes for this session only," adjust your behavior in
the conversation without writing anything. The change does NOT persist —
that's what the links above are for.

## Explicit checkpoint and recall

This plugin ships two user-invokable slash skills for surfaces where
plugin hooks don't fire (Cowork, some IDE extensions):

- `/checkpoint [topic]` — summarize what was memory-worthy this session
  and store it. Use when the user says "save what we talked about",
  "checkpoint this session", "store today's progress", or near the
  natural end of a substantive session.
- `/recall [topic]` — load relevant Seaglass context to prime the
  conversation. Use as a manual `SessionStart` equivalent.

Per-turn writes still happen through the normal `store_memory` /
`store_document` path described above; the `/checkpoint` skill is for
end-of-session bulk capture, not for replacing per-turn writes.

## Correcting stored memory (retirement)

Memory self-corrects through retirement: a retired row is kept as a labeled
tombstone (visible in search, out of synthesis). Three cases, one rule each:

- **The user gives you the newer fact** ("actually Ada moved to platform"):
  search for the stale memory, then `store_memory` the new fact with
  `supersedes: [<old_id>]`. One write captures the correction and retires what
  it replaces. Do not use `update_memory` for this.
- **The fact was never true and nothing replaces it** ("delete that, I never
  said that"): `update_memory` with `action: "retract"`. Always fill `note`
  with why; the note is what future sessions see on the tombstone. Retract is
  only for corrections with no replacement: if you are about to store the
  corrected fact anyway, do NOT retract-then-store as two calls — the one
  `store_memory` with `supersedes` keeps the old fact linked to its
  replacement.
- **A fact is merely old but still your latest knowledge**: leave it alone.
  Recency is carried by `event_time`; there is no "outdated" flag.

Other `update_memory` actions: `supersede` (retire retroactively when the
newer memory already exists; pass `successor_id`), `flag_sensitive` /
`flag_private` (audience correction), `redact` (destroy content — sparingly).

If a `store_memory` response includes `retired_match`, your new fact resembles
a retired claim. Do not ignore it: either the source you're reading is stale
(withdraw — retract the memory you just wrote), or the fact genuinely came
back (declare the reversal — `update_memory` supersede the matched tombstone
with your new memory as successor). Ask the user when unsure.

Synthesis re-runs automatically after any retirement.
