# Sensitivity handling — `<private>` tags and the three levels

## The three sensitivity levels

| Level | Feeds synthesis? | Visible in general reads? | Visible in `search`? |
|---|---|---|---|
| `normal` | Yes | Yes | Yes |
| `sensitive` | Yes (as summaries) | Flagged | Flagged |
| `private` | **No** | **No** | Only with `include_private: true` |

Each memory and document carries one of these levels. The default is `normal`.

## The `<private>` tag — server-forced

When you call `store_memory` or `store_document`, Seaglass scans the
`content` body for `<private>...</private>` blocks. If any are present,
the server forces `sensitivity: private` regardless of what your tool call
declared.

**You cannot override this from the client.** Even if you pass
`sensitivity: "normal"`, the presence of `<private>` tags wins.

The tags are *retained* in storage so the admin inspector can render the
private sections explicitly — they are not stripped.

### Example

The user says: "Tom is on the Q3 team. `<private>`He missed three deadlines
this quarter.`</private>` Anyway, his timeline looks tight."

Your call:

```bash
seaglass memory store \
  --page Tom --type people \
  --content "Tom is on the Q3 team. <private>He missed three deadlines this quarter.</private> Anyway, his timeline looks tight." \
  --sensitivity normal   # <-- ignored; server forces "private"
```

The DB row stores `sensitivity = "private"`. The whole content (including
the private block) is preserved.

## When the user implies private without using the tag

If the user says any of:

- "don't remember this"
- "off the record"
- "between us"
- "keep this private"
- "this is sensitive — just for me"

…pass `--sensitivity private` on the write. (You don't need to add
`<private>` tags yourself — the flag alone suffices when the content
doesn't contain inline private blocks.)

## When `sensitive` is the right level (not `private`)

`sensitive` is for things the user has shared but might not want
casually included in every response. Examples:

- Compensation details ("I make $X").
- Health details that are factual.
- Personal life events.

These still feed synthesis (so the wiki page knows about them) but get a
visible flag in the admin UI and in `search` output. The user can
review what's been categorized this way.

## When to pass `--include-private` on a read

**Only** when the user has explicitly asked for their private notes. Examples:

- "What private things have I noted about Tom?"
- "Show me the private memories about the Q3 launch."

Otherwise, omit the flag. Never pass `--include-private` reflexively
or to "be helpful" — the user enabling private mode is a deliberate act.

## Cross-client behavior

Private content does **not** appear in `seaglass search` results (or any other
client's read calls) by default. This is enforced server-side, not
client-side — even a misbehaving client can't surface private memory
unless `--include-private` is passed.

## Synthesis exclusion

The synthesis worker drops `private`-sensitivity memories before assembling
its prompt. This means a wiki page about "Tom" will never include the
private block, even if the founder views the page. The private content is
visible in the admin UI's storage inspector at the row level.

## Audit trail

Every memory and document stamps full provenance — the agent, session, and
source — so the founder can audit what was captured under what
circumstances. Private content has the same provenance trail as normal
content.
