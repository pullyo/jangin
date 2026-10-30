# operator

**English** · [한국어](README.ko.md)

**An operations loop for AI agents that does little, but never breaks its rules.**
Let your coding agent run the day-to-day of a small business or side project (research → drafts → posting, emailing,
deploying) while every action that leaves your machine goes through you, and an interrupted run picks up where it stopped.

operator is an [Agent Skill](https://agentskills.io) plus a small, dependency-free Python CLI (`op`). The same folder works in
Claude Code, Codex CLI, Cursor, Gemini CLI and other tools that read the Agent Skills format.

---

## Why

"AI employee" products are compelling because they don't just *build* things, they keep *running* them. What makes them
safe is not the model but the machinery around it: approvals, checkpoints, validation. Most agent plugins only *ask* the
model to "get confirmation first", which works most of the time. operator turns those requests into rules the agent
cannot get around:

| Without operator | With operator |
|---|---|
| "Ask before posting" in a prompt (usually followed) | Posting, emailing, deploying, paying and deleting are **blocked by a hook** and routed to an approval queue |
| The agent re-reads the chat to guess where it was | Every step is checkpointed in `state.json`; a new session resumes at the exact step |
| Only code gets tested | Every output is validated (post length, placeholders, banned words, sources, build) before it can even reach the queue |
| Every call goes to the big model | Classification and summaries can go to a local model; judgment and writing stay with the agent |

It is designed for solo founders and indie developers: small enough to read in one sitting, strict where it matters.

## How it works

```
 you ──"run a pass"──▶ agent ──▶ research ──▶ draft ──▶ op verify ──▶ op pending add ──▶ .operator/pending/
                         │                                   │ fail → fix the draft
                         │  tries `git push`, `curl -X POST`, `wrangler deploy` …
                         └──▶ op guard (hook) ──✋ blocked ──▶ "put it in the approval queue"

 you (your own terminal or phone) ──▶ op pending approve 0001 ──▶ .operator/approved/
 agent ──▶ op send 0001 ──▶ runs exactly the approved action (e.g. op deliver 0001 → posts to X) ──▶ .operator/sent/
```

Approvals only work from an interactive terminal, so the agent's own shell tool can never approve anything.

## Features

| | Command | What it does |
|---|---|---|
| Approval gate | `op guard` (PreToolUse hook) | Blocks outbound and irreversible commands, edits to the queue, and shell tricks that move queue files. Applies to `cd project && …` and `git -C project …` too |
| Resumable passes | `op pass` | A pass is research → draft → queue → report, with a step limit instead of "credits". Survives crashes and new sessions |
| Validation gate | `op verify` | Per type rules: posts (channel length), email (to/subject), research (≥3 source URLs), site (build must succeed) |
| Real delivery | `op deliver` | X, Threads, email (SMTP) and webhooks (Slack/Discord). Only for approved tickets; tokens are read from outside the project |
| Remote approval | `op serve`, `op notify` | Approve or reject from your phone over your Wi-Fi with a one-time link; get a push with the number of waiting items |
| Learning from "no" | `op feedback` | Rejection reasons are collected and read before the next draft |
| Model routing | `op llm` | Sends narrow tasks to a local OpenAI-compatible model (e.g. Ollama), falls back to the agent |

## Quick start (5 minutes)

**1. Install** (pick one)

```text
# Claude Code — plugin, hook is wired automatically
/plugin marketplace add pullyo/operator-skill
/plugin install operator@operator-skill
```

```bash
# Any tool, by hand: links the skill into ~/.claude, ~/.codex, ~/.cursor, ~/.gemini (whichever exist)
git clone https://github.com/pullyo/operator-skill
sh operator-skill/skills/operator/install.sh
sh operator-skill/skills/operator/install.sh --print-hooks   # hook snippets for Claude Code / Codex / Cursor / Gemini CLI
```

Without a hook the skill still works, but blocking becomes an instruction instead of a guarantee.

**2. Turn it on for one project**

```bash
alias op="$PWD/operator-skill/skills/operator/scripts/op"   # or put scripts/op on your PATH
cd ~/my-product && op init                                 # creates .operator/ — the guard only acts where this exists
```

**3. Talk to your agent** (open a new session in that folder)

> Plan my product with operator. Channels: X and Threads, short and friendly.
>
> Run one pass: a launch post for each channel.

**4. Review and approve — yourself**

```bash
op pending list
op pending show 0001
op pending approve 0001          # or: op pending reject 0001 --reason "too stiff"
op serve --lan                   # optional: approve from your phone instead
```

**5. Ship it**

> Send 0001.

The agent runs `op send 0001`, which executes only the command you approved. Start with a webhook to a private
Discord or Slack channel to see the whole loop before connecting real accounts.

## Commands

| Command | Who | Purpose |
|---|---|---|
| `op init` · `op status` | anyone | Create the workspace; show the current pass, queue and rejections |
| `op pass start/next/done/fail/end` | agent | Run and checkpoint a pass |
| `op verify <file> --type …` | agent | Check a draft before queueing |
| `op pending add <file> [--action "cmd"]` | agent | Validate and queue a draft (x/threads/email/webhook get `op deliver <id>` automatically) |
| `op pending list/show` | anyone | Read the queue |
| `op pending approve <id> [--action "cmd"]` · `reject <id> --reason …` | **you**, interactive terminal | Decide |
| `op send <id>` | agent | Run the approved action, nothing else |
| `op serve [--lan]` · `op notify` | **you** / agent | Phone approval page · push the number of waiting items |
| `op feedback` | agent | Read recent rejection reasons |
| `op deliver --check` | anyone | Show which channels have tokens (never prints values) |
| `op guard check [--cwd DIR] "cmd"` | anyone | Would this command be blocked? |
| `op llm --role summarize …` | agent | Route a narrow task to a local model |

## Safety model

**Enforced** (by the hook and by `op` itself):

- Outbound and irreversible commands are blocked: social API posts, mail, `curl` POST/PUT/DELETE to remote hosts, `git push`
  (including `git -C … push`), `vercel/netlify/wrangler/fly deploy`, `npm publish`, Stripe charges, domain purchases,
  recursive deletes, `git push --force`, `DROP TABLE`.
- The queue (`.operator/pending|approved|sent|rejected`) can only change through `op`. Writing to it with an edit tool or with
  `mv`/`cp`/`>`/`sed -i`/a Python one-liner is blocked. Read-only commands such as `cat`, `ls` and `grep` are allowed.
- `op pending approve/reject` and `op serve` refuse to run without an interactive terminal. An agent cannot run them, even
  from a copied script.
- `op send` runs only the action recorded on the approved ticket. A different command is refused; a ticket with no action
  cannot be sent; actions that call `op pending`/`op send` are refused.
- Domain purchases and payments are never queued: you do those yourself.

**Not covered** — be aware:

- Tools without hooks only get the rules as instructions.
- Tokens live on the same machine as the agent. The guard blocks outbound requests, but this is not a secret vault: use
  tokens scoped to posting only.
- `op serve --lan` is plain HTTP on your local network with a one-time token. Use it on trusted networks (or a private VPN
  such as Tailscale), never exposed to the internet.
- The guard reads commands; paths built from variables (`cd $HOME/x`) are judged from the session folder only.

## Limits

- operator does not run by itself. Each pass starts when you (or your OS scheduler) ask for it —
  see [scheduling](skills/operator/references/scheduling.md).
- It does not build your brand, website or mailbox, and it does not handle payments.
- X user tokens expire quickly; operator does not refresh them. See [channels](skills/operator/references/channels.md).

## Repository layout

```
operator-skill/
├── .claude-plugin/        Claude Code plugin + marketplace manifest
├── .codex-plugin/         Codex plugin manifest
├── hooks/hooks.json       Claude Code plugin hook (approval gate)
├── tests/                 End-to-end tests that drive the real `op` process
└── skills/operator/       The skill (Agent Skills format)
    ├── SKILL.md           What the agent reads
    ├── scripts/op.py      The CLI — Python 3.8+, standard library only
    ├── references/        Pass flow, guard / validation rules, channels, scheduling, design notes
    ├── assets/            Draft templates, per-tool hook snippets, launchd template
    └── install.sh         Multi-tool installer
```

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests feed the same hook JSON that Claude Code and Codex send into the real `op` process, and post to a local fake
X/Threads API to check delivery without touching real accounts.

## Background

The design was inspired by how [Foundable](https://foundable.com) describes its AI employee publicly
(build → run → earn, everything waiting for your OK). operator is an independent implementation and is not affiliated with
Foundable. Design notes: [references/foundable-research.md](skills/operator/references/foundable-research.md).

## License

MIT
