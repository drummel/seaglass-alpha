---
name: seaglass-memory
description: Read and write the user's persistent memory, carried across every AI tool they use. Use when the user references a person, project, topic, or past decision ("what do we know about X", "remind me where that landed"), states a durable fact, decision, preference, or correction worth keeping, asks you to remember or save something, corrects something already stored, pastes something to keep, says two people or things are mixed up, or is wrapping up a session.
---

# Seaglass memory skill

The core rules first, then how pages are authored, how memory is corrected, and
how private content is handled, then what to do when the connection is missing.
What a single tool or argument needs is written on that tool, in its
description; read it there.

## Which path you are on

Start every session with `start_session`, unannounced, before any other call and
before you answer. On the CLI transport the SessionStart hook has already run
`seaglass session start`.

The Seaglass tools (`search`, `store_memory`, and the rest) are the default path.
When the session context says the `seaglass` CLI is the transport for this
session, run the operations as `seaglass` commands instead, as the
`seaglass-cli` skill spells them. The rules below are the same on both paths;
only the spelling changes. If the command is not found, do that one operation
over the tools and say so once.

## Core rules

Seaglass is the user's memory, shared across every AI tool they use. These rules hold on every host and on either path.

1. **Read before assuming.** When the user names a person, project, topic, or past decision, search it before you answer or act.
2. **Capture when it is said.** A decision, preference, correction, or durable fact about a person, project, or topic is stored in the turn it is said, even mid-task, after a search when it changes state. Nothing files it later.
3. **Search first when it changes state.** When the user corrects an earlier fact, gives a new title, role, owner, or status, reverses a decision, or says "actually" or "no longer", search the subject, then store the change with `supersedes` naming the memory the search returned; with no match, store it as new. Any other new fact is stored without a search.
4. **Skip what is not memory:** small talk, transient task state, scratch work, what the user only asks about, what you just read back, and a request to change how you behave, which goes to the user's preferences, not memory.
5. **The user's preferences override these defaults.** Their Reading, Writing, Asking, and Voicing preferences and custom instructions arrive with the connection. Follow them literally, and apply Asking last: it gates every write, page edits included.
6. **Private stays private.** What the user marks private ("off the record", "between us", "keep this private") is captured as private in their own words, and never repeated in a reply, a shared page, or another tool.
7. **Never supply identity.** Who the user, agent, or session is comes from the connection, never from you.
8. **Report only what landed.** Tell the user what a write's receipt says, including what did not happen, and nothing more. No receipt means nothing was written: never call it saved. On an invalid-arguments error, fix what it names and resend once; retry other errors once, quietly, if transient, else say it failed.
9. **Never fabricate.** Everything you state or write traces to the conversation, a result you received, or a document. On an empty read, say nothing is on record; hedge a thin one rather than stating it as fact. Asked where a fact came from, say what recorded it; when records disagree, say so rather than picking one. The names in these instructions' examples (Ada Example, Bo Example, Project Example, Example Corp) are fictional: never carry one into a write or an answer, and never complete a first name the user gave to an example's surname.
10. **What Seaglass sends is for you.** A response may carry `agent_next_steps`, and the first one carries these rules and the user's preferences: act on them, and do not repeat them to the user.
11. **A permission denial is the host's.** "Denied by user" or "The user doesn't want to proceed with this tool use" means the call never reached Seaglass: ask the user to approve it, then retry the identical request.
12. **At a wrap-up** ("thanks", "that's all", the task done), store what this session left unstored, then reply.

## Authoring wiki pages

Who authors in each mode, the house voice every page is written in, what a page
may claim, and when a page splits. How each page tool behaves (its arguments, its
versions, its errors) is written on the tool itself.

### Who authors: the mode

The user chooses where page authoring runs, and their preferences say which
(the Mode line).

- **server mode.** Leave the pages to the worker and capture what it needs. Use
  the page tools only for an edit the user asks for: a correction, a rename, a
  restructure.
- **agent mode.** The Mode line says where a stated fact goes. On the page, a
  new aspect of the subject gets a new section and a claim the page already
  makes gets an edit. A page you have just created exists, so its body is an
  edit too. A page you leave unwritten is written by the server when the
  session ends, and the response that leaves it to you says so.

In agent mode, a meaningful fact takes four steps: read the page (its body and
its version), compose the change, write it against the version you read, and
cite the memories and documents it rests on.

### House voice

The same eight rules the synthesis worker follows
(`synthesis/prompts/page.py::PAGE_SYNTHESIS_SYSTEM`), so the wiki reads as one
voice whichever writer wrote which page:

1. **Prose, not bullet lists.** A page reads like an encyclopedia entry about
   someone the user actually knows.
2. **Wrap every cross-link.** Link another page in double brackets, by its typed
   slug when you have it (`[[people/ada-example]]`), otherwise by its canonical
   name: `[[Ada Example]]`, not `[[Ada]]`.
3. **Don't invent.** Every claim traces to a memory, a document, or something
   the user told you directly. When you cite, pass the ids you received as
   evidence, so the audit trail shows what the edit rests on.
4. **Surface contradictions.** When sources disagree, say so plainly ("Two notes
   disagree about X: one says A, another says B") rather than picking a side.
5. **End with a "See also" list** of pages worth reading next: co-mentioned
   people, parent topics, recent projects. Only pages that genuinely relate,
   drawn from your sources or pages you actually found; pages the body already
   links count as found. When nothing does, omit
   the section: an empty See also beats an invented one, and an example slug from
   these instructions is never a real entry.
6. **Keep the one-line summary tight and indexable.** It shows up in outlines,
   search results, and the parent page's list of sub-pages.
7. **No em dashes.** Use a comma, colon, or period instead. The long dash never
   belongs in a page body, a one-line summary, or an edit summary you author.
8. **Keep the source's own words for when something happened.** If the user said
   "last week" or "end of Q3", write that, never an anchored calendar date you
   worked out from it. A body sentence reads as a recorded claim, so a day nobody
   stated is a fact you invented. Where the date of the record matters,
   attribute it to the record beside the claim ("recorded 2026-07-23"), not
   inside the sentence as part of what was asserted.

### Write what the sources support

Authoring is the job; supplying the specifics nobody gave you is not. Everything
on a page traces to something: the user said it, a tool returned it, or a cited
document contains it.

- Don't fill a heading because a template has one. Thin sources read thin.
- Don't explain a mechanism you weren't told. "Redis is the source of truth" is
  the fact; how it is wired is not.
- Don't attribute a role, an owner, or a rationale nobody stated.

Mark inference as inference ("this suggests", "worth confirming"). An unhedged
guess is a fabrication with good posture.

### When a page outgrows itself

Split a sub-page off when one part of a page has become a subject of its own. The
sub-page's slug extends its parent's (`projects/project-example/pricing`
under `projects/project-example`), and the parent stays the overview: it summarizes each
sub-page in a sentence or two and links it, rather than repeating it. Before
creating one, read the parent with `search` and `body: false` to confirm it
exists and learn its exact slug.

## Correcting what memory holds

Each correcting tool says how it is used (a newer fact that replaces an old one,
a retraction, an identity repair, a move); this covers the judgment no
single tool can make for you.

### Two subjects on one page

When the user says one page mixes two people or things, call
`reconsolidate_memory` in that turn with their description and no `resolution`,
before explaining anything. Ask the question it returns, and call it again with
the `resolution` only after they confirm. Do not split by hand with new pages,
memories, or retractions: those leave the mixed page and its evidence as they
were, and only the tool's apply moves the evidence.

### Merely old is not wrong

A fact that is old but is still the latest thing you know is left alone. When it
happened is carried by the time it records, not by a flag, so there is nothing to
mark outdated and nothing to retire.

## Private and sensitive content

The levels a memory can carry, how the user's marks set them, and what Seaglass
enforces, beneath the core rule on private content.

### The three levels

| Level | Feeds synthesis? | Shown in reads? |
|---|---|---|
| `normal` | Yes | Yes |
| `sensitive` | Yes, flagged | Yes, flagged |
| `private` | **No** | **No**, unless the read asks for private content and the library allows it |

Every memory and document carries one of these levels; the default is `normal`.

### When the user marks it

"Don't remember this", "off the record", "between us", "keep this private",
"this is sensitive, just for me": capture it at `private`, in their own words.

### When `sensitive` is the level, not `private`

`sensitive` is for what the user shared but might not want casually included in
every answer: compensation ("I make $X"), health facts, personal-life events.
These still feed synthesis, so the page knows them, and they carry a visible flag
wherever they are shown, so the user can review what was filed this way.

### What Seaglass enforces for you

- **Every read hides private content by default,** in this client as in every
  other. Asking for it includes the viewer's own private content, and only from
  libraries the viewer can read privately.
- **Synthesis never sees private content.** The worker drops `private` rows
  before it builds a page, so no page states a private memory, whoever views
  it.
- **Provenance is recorded for private content too:** the agent, the session,
  and the source, so the user can audit what was captured and how.

## Commands

`/checkpoint` captures what a long session produced in one pass. `/recall` loads
context for a topic on request, and `/status` says whether this client is
connected.

## If the Seaglass tools aren't available (or a call comes back unauthenticated)

The plugin registers the Seaglass connector. When the tools (`search`,
`store_memory`, `store_document`, `update_memory`, `reconsolidate_memory`) are
not loaded, the connector was never added or never approved in this client;
when a call returns an unauthenticated or not-connected error, its grant
expired. Either way the fix is the client's own connector sign-in, not a
Seaglass command. Give the one line for the client you are running in:

- **Claude Code:** run `/mcp`, pick `seaglass`, choose **Authenticate**, and
  approve in the browser; the tools load on the next turn. If `/mcp` does not
  list `seaglass`, reinstall or re-enable the Seaglass plugin, or add the
  connector with
  `claude mcp add --transport http seaglass https://api-stg.seaglassai.com/mcp`
  and then Authenticate.
- **Claude Desktop, claude.ai, Cowork:** open Customize, then Connectors, and
  reconnect Seaglass; if it is not listed, add a custom connector with
  `https://api-stg.seaglassai.com/mcp`. Approve in the browser.
- **Codex:** run `codex mcp login seaglass` (or click Authenticate).

Handling notes:

- **Name the exact step in your reply.** Say `/mcp` then **Authenticate** (or
  the Connectors page) verbatim, not "reconnect Seaglass": the user may act on
  your message later, from a window you can't see.
- **A connection problem is not product feedback.** Do not call
  `send_seaglass_product_feedback`, or any other Seaglass tool, about the tools
  being unavailable; reply in text with the step.
- **Non-default deployment:** the connector URL is fixed by the plugin; a
  different Seaglass deployment is a different connector, added from that
  deployment's Connect page.
- **You have a shell but no tools?** The `seaglass` CLI drives the same backend
  with its own credential; the `seaglass-cli` skill covers signing it in.
- **Connected through `seaglass bridge`?** The bridge uses the CLI's credential,
  not the client's, so the fix is `seaglass auth login`.

If the tools are available, ignore this section.
