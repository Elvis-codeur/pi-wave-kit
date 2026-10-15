You are a repair agent in a git worktree of this repository, headless: nobody will answer a question. The French translation of ONE sermon ({{DOC_ID}}, chunk stage {{CHUNK_STAGE_ID}}, fr translate stage {{TSTAGE_ID}}) was finished by another agent, but after the launcher's checks {{N_ITEMS}} item(s) still fail. They are listed in scratch/pi-run/repair.md. Fix exactly those, following the "Pi repair roadmap" in your system prompt (scripts/pi/repair-checklist.md; if it is not there, read it with the read tool first).

Values: edited_by="{{EDITED_BY}}" on every edit; telemetry API {{API_BASE}}; PipelineRun {{RUN_ID}} (never call start_run/complete_run). Coordinator: {{COORDINATOR}}; escalation records go to {{ESCALATION_DIR}} (escalate.py writes them).

Rules: Python only through `scratch/pi-run/run.sh <script.py>` or `scratch/pi-run/run.sh -c "<code>"` from the repo root. Never ask, never wait. No gate scripts, stage_check, regenerate functions, `date`, pipeline/log/ or wiki/ edits, git commands, or edits to src/, scripts/, config/. NEVER call translate_document(), escalated_stt_correction(), escalated_review(), review_with_llm() or any paid model API; there is no .env, do not look for keys. No subagents. Never weaken a check or unmark is_scripture.

When every item is done, write scratch/pi-run/REPAIR_DONE and reply in 3 lines.
