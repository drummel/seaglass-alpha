#!/bin/bash
# Hermes post_llm_call hook for Seaglass.
#
# Reserved shim: Hermes fires this after each LLM call — the natural place for a
# post-turn auto-capture trigger. Kept a no-op for the foundation (capture is
# agent-driven via the tools/CLI, not hook-forced) so it never adds latency or
# double-records against Hermes' own memory. Wire a capture call here once the
# capture-policy contract is settled. Confirm the hook payload against live docs.
set -uo pipefail
exit 0
