# Coding agents: per-client keys, shared logins, programmatic control

Researched 2026-10-30 (issue #11) for two needs: billing work for different clients on different
API keys, and running pi-wave-kit-style waves (launch many, steer, collect results and cost) on
agents other than pi.

Versions installed on the owner's laptop when this was checked: pi 1.4.0, codex-cli 0.146.0,
Claude Code 2.1.314, opencode 1.17.13. Facts marked **(local)** were checked against those
binaries' own `--help` or by running them; the rest come from the sources at the bottom.

## 1. A different API key per launch

Every agent can take its key from the process environment, so the caller picks the key per
launch. Each also has a config-home variable, which gives a client its own stored credentials.

| Agent | Key for one launch | Separate stored credentials |
|---|---|---|
| pi | `--api-key <key>` or the provider's variable (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, ...) **(local)** | `PI_CODING_AGENT_DIR` (default `~/.pi/agent`, holds `auth.json`) **(local)** |
| Codex | `CODEX_API_KEY` for `codex exec` **(local: the binary reads it)**; a custom provider names its key variable with `model_providers.<id>.env_key` | `CODEX_HOME` (default `~/.codex`, holds `auth.json`), then `codex login --with-api-key` once |
| Claude Code | `ANTHROPIC_API_KEY` (always used under `-p` when set), or an `apiKeyHelper` script passed with `--settings` | `CLAUDE_CONFIG_DIR` |
| OpenCode | provider `options.apiKey` as `"{env:VAR}"` or `"{file:path}"` in a config file; `client.auth.set()` on a running server | stored keys live in `~/.local/share/opencode/auth.json` |
| DeepSeek Harness | `DEEPSEEK_API_KEY` in the environment, project `.env`, or `$DSH_HOME/.env` | `DSH_HOME` (default `~/.dsh`, holds `.credentials.yaml`) |

pi-wave-kit's `agents.start_agent(..., env={...})` passes such variables to one job only (#12).

**Splitting cost does not need one key per client.** The cost ledger prices every call from its
token counts, so tagging each run `client:<name>` splits the bill on one shared key. Separate keys
matter when the client pays the provider directly, or for provider-side spending caps per client.

## 2. Logging in once for many parallel sessions

- **API keys are read at start-up, not "logged in".** Ten parallel sessions read the same exported
  variable or the same config home; nothing is repeated per session.
- **Subscription logins** (Copilot in pi, ChatGPT in Codex, Claude Pro/Max in Claude Code) are
  stored once in a file and shared by every session using that config home. Codex refreshes its
  token itself during use. Claude Code has `claude setup-token`, a long-lived token meant for
  automation (`CLAUDE_CODE_OAUTH_TOKEN`).
- Risk with shared subscription logins: many processes refreshing one stored token at the same
  moment can race. Client work billed to a client should use API keys anyway.
- **(local)** Codex on the owner's ChatGPT login rejects its own configured default model
  (`gpt-5.6-sol`: "not supported when using Codex with a ChatGPT account"); `gpt-5.6-luna` works.
  Pass a model explicitly in automation.

## 3. Programmatic control (what replaces pi-messenger and pi subagents)

pi-wave-kit drives pi through `pi -p` jobs, `--session` resume, the pi-messenger mesh and pi's
subagent extension. The others have their own channels:

| Agent | One job, JSON out | Resume / steer with a new message | Long-lived control |
|---|---|---|---|
| pi | `pi -p --mode json` | `pi -p --session <file>` | `--mode rpc`, pi-messenger |
| OpenCode | `opencode run --format json` **(local)** | `opencode run --session <id>` | `opencode serve` (HTTP + typed SDK, many sessions per server), `opencode acp` |
| Codex | `codex exec --json` **(local)** | `codex exec resume <id>` **(local)** | `codex app-server` (JSON-RPC), `codex mcp-server` |
| Claude Code | `claude -p --output-format json` **(local)** | `claude -p --resume <id>` | Agent SDK (Python/TS), `--input-format stream-json` |
| DeepSeek Harness | `dsh --profile headless "job"` | not documented for headless | `dsh --profile sdk` (JSON-RPC stdio, Python wheel), `--profile acp` |

ACP (Agent Client Protocol) is the shared protocol: OpenCode and DeepSeek Harness speak it
natively, others through adapters.

What pi-wave-kit implements (#12): the one-job + resume column for pi, OpenCode, Codex and Claude
Code behind one interface, so `run_wave` can schedule any of them. Live steering of an
interactive session (typing into it while it runs) is agent-watch-daemon's job; it already does
that through `screen` for all four tools.

### Usage reported by each agent (**local**, captured 2026-10-30)

| Agent | Session id | Token fields | Cost reported |
|---|---|---|---|
| OpenCode | `sessionID` on every event | `step_finish.part.tokens`: `input`, `output`, `reasoning`, `cache.read`, `cache.write` (input excludes cache) | `step_finish.part.cost` |
| Codex | `thread.started.thread_id` | `turn.completed.usage`: `input_tokens` (includes cached), `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens` | none |
| Claude Code | `session_id` in the final `result` object | `usage`: `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`; model name is the key of `modelUsage` | `total_cost_usd` |

Codex reports no cost, so a wave cap on Codex jobs counts $0 unless a cost is supplied; the
ledger still prices the logged tokens from its own pricing table.

## 4. DeepSeek Harness (`dsh`)

DeepSeek's own agent runtime, MIT licensed, repository `deepseek-ai/deepseek-harness`, published
August 2026; still a developer preview with announced breaking changes. Everything is a plugin;
it ships a web UI (`npx @deepseek-ai/dsh web`, port 3080), desktop apps (v0.2), and launch
profiles: `headless` (one job, prints the answer, exits), `sdk` (JSON-RPC over stdio, also as a
Python package), `acp`, plus a `subagent` package.

Login: a DeepSeek API key, saved on the web UI's Models page (`$DSH_HOME/.credentials.yaml`) or
exported as `DEEPSEEK_API_KEY`. Since v0.2.1-alpha.2 a saved key wins over an exported one, and
the `headless` profile ignores saved keys entirely: for batch jobs, export the key and run
`dsh headless "<task>"`. (Read from the repository's own upgrade guide and `apps/cli/README.md`
at commit `ce7073d5`, 2026-10-30.)

Not yet a pi-wave-kit backend: its headless profile documents no JSON output or resume, and its
interfaces are still changing. Revisit when it stabilises.

## Sources

- Codex authentication: https://learn.chatgpt.com/docs/auth
- Codex environment variables (third party): https://codex.danielvaughan.com/2026/06/03/codex-cli-environment-variables-runtime-configuration-headless-ci-container-deployment/
- Claude Code settings: https://code.claude.com/docs/en/settings
- Claude Code environment variables: https://code.claude.com/docs/en/env-vars
- Claude Code headless: https://code.claude.com/docs/zh-CN/headless
- OpenCode providers: https://opencode.ai/docs/providers/
- OpenCode server: https://opencode.ai/docs/server/
- OpenCode SDK: https://opencode.ai/docs/de/sdk
- DeepSeek Harness repository: https://github.com/deepseek-ai/deepseek-harness
- DeepSeek Harness desktop release: https://gigazine.net/gsc_news/en/20261005-deepseek-harness/
- DeepSeek Harness overview: https://www.digitalapplied.com/blog/deepseek-harness-open-source-agent-framework-2026
- DeepSeek Harness how-to: https://docs.kanaries.net/topics/AICoding/deepseek-harness-how-to-use
