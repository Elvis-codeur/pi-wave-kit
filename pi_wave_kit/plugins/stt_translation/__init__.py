"""The STT/translation plugin: a bundled example of using pi_wave_kit for the EXACT real-world case it
was extracted from -- speech-to-text verification + theological document translation, Pi/DeepSeek
workers under a budget cap, a coordinator, an escalation protocol. See README.md in this directory for
what's ported (generic pure functions + 8 concrete stage-check conditions) vs. what you still have to
wire up (your own chunk/document data access -- agentic_doc's, or an equivalent).

The prompts/ directory holds the REAL, verbatim prompt/checklist/glossary/review-examples files this
pipeline used in production (not a rewritten summary) -- data you can hand to a worker as-is, or copy
and adapt for a different document/translation domain."""
