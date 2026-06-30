#!/bin/bash
# Hermes pre_llm_call hook for Seaglass.
#
# Reserved shim: Hermes fires this before each LLM call. Seaglass does its
# context injection at on_session_start (cheaper than per-call), so this is a
# deliberate no-op placeholder — present so the four-hook adapter is complete
# and a future per-call recall can land here without changing the manifest.
# Never disrupts a turn.
set -uo pipefail
exit 0
