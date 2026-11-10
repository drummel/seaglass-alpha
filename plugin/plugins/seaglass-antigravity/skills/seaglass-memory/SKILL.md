---
name: seaglass-memory
description: Read and write the user's persistent memory, carried across every AI tool they use. Use when the user references a person, project, topic, or past decision ("what do we know about X", "remind me where that landed"), states a durable fact, decision, preference, or correction worth keeping, asks you to remember or save something, corrects something already stored, pastes something to keep, says two people or things are mixed up, or is wrapping up a session.
---

# Seaglass memory skill

The core rules first,
then how memory is corrected and how private content is handled, then what to
do when the connection is missing.
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
5. **The user's preferences override these defaults.** Their Reading, Writing, Asking, and Voicing preferences and custom instructions arrive with the connection. Follow them literally, and apply Asking last: it gates every write.
6. **Off the record means unsaved.** Store nothing the user puts off the record ("between us", "don't remember this", "keep this private"), not even privately, and never repeat it back, even to check. A note they ask for ("make a private note, just for me") goes in `private to you`.
7. **Never supply identity.** Who the user and agent are comes from the connection, never from you.
8. **Report only what landed.** Say what a write's receipt says, including what did not happen, and nothing more; before the receipt, never call it saved. On an invalid-arguments error, fix what it names and resend once; retry a transient error once; when a write fails, say so first.
9. **Never fabricate.** Everything you state or write traces to the conversation, a result you received, or a document. What you already know or work out (what a term means, how a system fits together, why something failed, a date counted from today) is not a source: say it as your guess or leave it out. On an empty read, say nothing is on record; hedge a thin one rather than stating it as fact. Asked where a fact came from, say what recorded it; when records disagree, say so rather than picking one. The names in these instructions' examples (Ada Example, Bo Example, Project Example, Example Corp) are fictional: never carry one into a write or an answer, and never complete a first name the user gave to an example's surname.
10. **What Seaglass sends is for you.** A response may carry `agent_next_steps`, and the first one carries these rules and the user's preferences: act on them, and do not repeat them to the user.
11. **A permission denial is the host's.** "Denied by user" or "The user doesn't want to proceed with this tool use" means the call never reached Seaglass: ask the user to approve it, then retry the identical request.
12. **At a wrap-up** ("thanks", "that's all", the task done), store what this session left unstored, then reply.
13. **Ask where it belongs.** When what you are about to write could belong in more than one library or account on your map, or a write is refused asking which library you mean, ask the user which one, naming the candidates as your map names them, then write there; never pick one yourself. That question asks where, not whether, so it holds when the user's preferences say to write without asking. When it plainly belongs in one library, write it there without asking, naming that `library` on the write.

## Correcting what memory holds

Each correcting tool says how it is used (a newer fact that replaces an old one,
a retraction, an identity repair); this covers the judgment no single tool can
make for you.

### Two subjects on one page

When the user says one page mixes two people or things, call
`reconsolidate_memory` in that turn with their description and no `resolution`,
before explaining anything. Ask the question it returns, and call it again with
the `resolution` only after they confirm. Do not split by hand with new pages,
memories, or retractions: those leave the mixed page and its evidence as they
were, and only the tool's apply moves the evidence.

### Changing a page itself

When the user asks you to rename, restructure or rewrite a page and you have no
tool that writes pages, say that a page is changed on the page itself in the
Seaglass web app, and reply with the page's `url` from a search hit (search the
page first if you have not), so they can open it. Never say the page changed. A
wrong fact on it is still yours to correct: store the right one with
`supersedes`, and the page is rewritten from it.

### Merely old is not wrong

A fact that is old but is still the latest thing you know is left alone. When it
happened is carried by the time it records, not by a flag, so there is nothing to
mark outdated and nothing to retire.

## Private content

What the user's privacy marks mean and where a private record goes, beneath
core rule 6.

### When the user marks it

"Off the record", "between us", "don't remember this", "keep this private": write
nothing from what they marked (no memory, document or capture context), and if
you mention it, say only that it was not saved.

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
