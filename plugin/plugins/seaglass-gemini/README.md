# Seaglass for Gemini CLI

A [Gemini CLI](https://github.com/google-gemini/gemini-cli) extension that
connects Gemini to your Seaglass memory: the memory connector with browser
sign-in, the capture skill, session hooks, and a status command.

## Install

```bash
gemini extensions install drummel/seaglass-alpha --auto-update
```

Gemini shows what the extension can do and asks you to confirm. Start `gemini`
and approve Seaglass in the browser when it opens. Then run
`/seaglass-stg:status` to check the connection.

Update later with `gemini extensions update seaglass-stg`.

## What it adds

| Gemini surface | What Seaglass does there |
|---|---|
| MCP server `seaglass-stg` | The memory tools, signed in through the browser on first launch |
| `GEMINI.md` | Opens every session with `start_session` and sends kept facts to Seaglass |
| Skills | `seaglass-memory`, `checkpoint` and `seaglass-cli` |
| Commands | `/seaglass-stg:status`, `:recall` and `:checkpoint` |
| Hooks | Session start and end, and transcript capture when the `seaglass` CLI is signed in and capture is on (macOS and Linux) |

On Windows the extension ships without hooks, because Gemini runs them in
PowerShell there.

