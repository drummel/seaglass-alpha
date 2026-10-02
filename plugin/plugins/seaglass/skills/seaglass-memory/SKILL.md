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
3. **Search first when it changes state.** When the user corrects an earlier fact, gives a new title, role, owner, or status, reverses a decision, or says "actually" or "no longer", search the subject, even when the user gives the memory's id, then store the change with `supersedes` naming the memory the search returned; with no match, store it as new. Any other new fact is stored without a search.
4. **Skip what is not memory:** small talk and remarks about the moment, transient task state, scratch work, what the user only asks about, what you just read back, and a request to change how you behave, which goes to the user's preferences, not memory.
5. **The user's preferences override these defaults.** Their Reading, Writing, Asking, and Voicing preferences and custom instructions arrive with the connection. Follow them literally, and apply Asking last: it gates every write, page edits included.
6. **Off the record means unsaved.** Store nothing the user puts off the record ("between us", "don't remember this", "keep this private") and never repeat it, even to confirm. A private note they ask for ("just for me") goes in `private to you`.
7. **Never supply identity.** Who the user and agent are comes from the connection, never from you.
8. **Report only what landed.** Tell the user what a write's receipt says, including what did not happen, and nothing more. No receipt means nothing was written: never call it saved. On an invalid-arguments error, fix what it names and resend once; retry a transient error once; when a write fails, say so first.
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

The same eleven rules the synthesis worker follows
(`synthesis/prompts/page.py::PAGE_SYNTHESIS_SYSTEM`), so the wiki reads as one
voice whichever writer wrote which page:

1. **Write for readability.** A page reads like a reference entry on its
   subject, for a reader who has never seen it, possibly someone it is shared
   with. Use the form that reads most clearly, not the one the facts arrived
   in:
   - prose to explain what something is and why;
   - a numbered list for steps a reader follows in order, one step per item:
     a release done in four steps is a four-item list;
   - a list for options or several parallel points;
   - a table when several things are compared on the same attributes: three
     plans by price, seats and support are one row per plan and one column
     per attribute.

   Steps or a comparison the user gave you as sentences still become a list or
   a table. A list is never a dump of loose facts: each item is a complete
   thought, introduced by a sentence that says what it lists. Explain or leave out internal identifiers, code names, file
   paths and jargon that reader would not know. The first time the body uses a term a
   newcomer would not know (a tool, a protocol, an acronym, an internal name),
   say in a few words what it is, from what the sources say about it, in that
   same sentence; a link alone does not explain it. A term the sources don't
   explain stays named, described only by what it does in them ("the
   project's scripts run on Bun"), never defined from your own knowledge.
2. **Wrap every cross-link.** Link another page in double brackets, by its typed
   slug when you have it (`[[people/ada-example]]`), otherwise by its canonical
   name: `[[Ada Example]]`, not `[[Ada]]`. Linking keeps the page on its
   subject: when the page mentions a related subject that has a page of its
   own, keep it to a sentence and its link and leave its detail to that page.
   A sub-page gets an overview section instead (see When a page outgrows
   itself).
3. **Don't invent.** Every claim traces to a memory, a document, or something
   the user told you directly, and an explanation is a claim: what a tool or
   setting is or does comes from them or is not said, and a config or code
   block gets no gloss on its settings beyond what they give. Spelling out a
   standard acronym is fine. When you
   cite, pass the ids you received as evidence, so the audit trail shows what
   the edit rests on.
4. **Surface contradictions, in the subject's terms.** When sources disagree,
   say what is unsettled ("The launch date is unsettled: Q3 or Q4") rather than
   picking a side, and never describe the sources.
5. **Leave the page chrome out of the body.** The page already shows its title,
   sub-pages, a See also list (built from the pages the body links) and its
   sources, so the body has no heading repeating the title, no list of
   sub-pages and no See also section. Link related pages where the prose
   mentions them. A page with sub-pages gives each one a short overview
   section (see When a page outgrows itself), which is not a list.
6. **Keep the one-line summary tight and indexable.** It shows up in outlines,
   search results, and the page tree's list of sub-pages.
7. **No em dashes.** Use a comma, colon, or period instead. The long dash never
   belongs in a page body, a one-line summary, or an edit summary you author.
8. **Keep the source's own words for when something happened.** If the user said
   "last week" or "end of Q3", write that, never an anchored calendar date you
   worked out from it. A body sentence reads as a stated claim, so a day nobody
   stated is a fact you invented. Where it matters when the fact was known, put
   that date beside the claim as a dateline ("as of 2026-07-23"), not inside the
   sentence as part of what was asserted.
9. **Open with a lede.** Before any heading, a paragraph tells a newcomer what
   the subject is, why it matters and where it stands now, going beyond the
   one-line summary.
10. **Organize by aspect, not by date.** Sections follow what the page's
   collection description says a page of its kind records (for a project: its
   purpose, how it works, its decisions and why), most important first. The
   description is in the map of your libraries or the `seaglass://libraries`
   resource; take only the aspects it names, not its filing instructions. With
   no description, use the subject's own natural aspects. Write a section only
   for an aspect the sources say something about; one they don't cover gets no
   heading and no mention (a sub-page still gets its overview section, below).
   Keep a dated log only where the collection asks for
   dated entries. The lede and first sections carry what the subject is, why
   it matters and its main decisions; commands, settings, versions and file
   paths come after them and stay compact (several that share attributes fit
   a table), and one-off incidents and cosmetic changes get a sentence at most.
11. **Never describe how the page was made.** The body never mentions the
   sessions, captures, memories, notes or documents it was written from,
   sources agreeing or disagreeing, or synthesis, and never says what is or is
   not recorded ("not recorded", "documented only by"), and never points out
   what the page lacks ("not yet filled in", "no trigger has been stated"). A
   subject that is itself about memory or sessions is described like any
   other.

### What renders

- Sections are `##` and `###` headings at the start of a line. `edit_section`
  addresses one by its heading; `append_section` adds a new one at the end.
- Lists, tables, code fences with a language tag (```` ```python ````) and
  `[text](https://…)` links render. Code, and commands a reader runs one after
  another where every step is a command, go in one fence tagged with its
  language (```` ```bash ````, never a bare ```` ``` ````), which gets a label
  and syntax colors; a short note on a step goes beside the block, not between
  its lines. When some step is an action with no command given (clone the
  repo, open the settings page), the steps are a numbered list, each command
  inline in its step.
- Footnotes, task-list checkboxes, callouts and HTML show as literal text, and
  an image shows only as a link to it, so leave them out.

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
under `projects/project-example`), and the parent stays the overview: it leaves each
sub-page's detail to the sub-page and never lists its sub-pages (the page tree
does). Each sub-page gets a short overview section headed with its title, standing
where the aspect it covers would go: two to four sentences on what that part is,
where it stands when your sources say so (with a dateline only when they date
it), and what the sub-page covers, with the link. A sub-page's one-line summary
tells you what it covers; it is not a source for claims about it. When you have
nothing on a sub-page, its section is a sentence and the link. Lists, commands,
versions and step-by-step history stay on the sub-page, where they won't go
stale. Before
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

## Private content

What the user's privacy marks mean and where a private record goes, beneath
core rule 6.

### When the user marks it

"Off the record", "between us", "don't remember this", "keep this private": write
nothing from what they marked (no memory, document, page edit or capture
context), and if you mention it, say only that it was not saved.

### A private note goes in their private library

Privacy is the library: whoever can read a library reads everything in it, and
nothing on a single memory or document hides it. When they ask for a record
only they can see ("make a private note, just for me"), store it in their own
words in the library the map shows `private to you`, which no other member can
read. When the map shows no such library, say so and ask where it should go;
never put it in a shared library.

### Reading it back

Content from their `private to you` library is for the answer they asked for.
Keep it out of any draft, page or message for others, and when you decline to
use it, do not name what it says.

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
