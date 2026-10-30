# operator

**English** · [한국어](README.ko.md)

**A dedicated AI partner that helps you shape an idea, then develop it and manage its deployment, on your own machine.**
Shaping the idea comes first: your coding agent asks one question at a time, pushes back, researches and helps you decide
whether it is worth building. Then it builds the approved plan milestone by milestone and ships it through an approval queue,
and keeps announcing it and reading the numbers to suggest what to do next. Every move to the next stage and every action
that leaves your machine goes through you. Goal and roadmap: [VISION.md](VISION.md).

operator is an [Agent Skill](https://agentskills.io) plus a small, dependency-free Python CLI (`op`). The same folder works in
Claude Code, Codex CLI, Cursor, Gemini CLI and other tools that read the Agent Skills format.

---

## Why

"AI employee" products are compelling because they don't stop at *building* something: they help you decide what to build,
then keep *running* it. What makes them safe is not the model but the machinery around it: stages, approvals,
checkpoints, validation. Most agent plugins only *ask* the model to "get confirmation first" and assume the product
already exists. operator gives the agent a lifecycle to follow and turns the requests into rules it cannot get around:

| Without operator | With operator |
|---|---|
| Every session assumes a finished product and starts writing posts | The project has a recorded **stage** (discover → validate → build → operate → learn); the agent does the work of that stage, and only you move it on |
| "Ask before posting" in a prompt (usually followed) | Posting, emailing, deploying, paying and deleting are **blocked by a hook** and routed to an approval queue |
| The agent holds your API tokens | By default, **sending happens in your own process** the moment you approve; tokens live in the macOS Keychain and the agent is blocked from reading them |
| "It's done" | Milestones only complete when their test command actually passes; stage documents and drafts are validated before they count |
| The agent re-reads the chat to guess where it was | Every step is checkpointed; a new session resumes at the exact step |

It is designed for solo founders and indie developers: small enough to read in one sitting, strict where it matters.

## How it works

```
 discover ──▶ validate ──▶ build ──▶ operate ──▶ learn ──▶ (you pick: operate | build | discover)
 talk it       research,    milestones  daily passes  metrics vs.
 through       go / revise  that pass   to the queue  the success metric
 with you      / stop       their tests
        each arrow = `op stage advance`, run by you in your own terminal

 inside a stage:
 agent ──▶ research / draft / code ──▶ op verify ──▶ op pending add ──▶ .operator/pending/
   │  tries `git push`, `curl -X POST`, `wrangler deploy`, reading your tokens …
   └──▶ op guard (hook) ──✋ blocked ──▶ "put it in the approval queue"

 you (terminal, phone over Telegram, or browser) ──▶ approve 0001 ──▶ your process sends it ──▶ .operator/sent/
```

Stage moves and approvals only work from an interactive terminal (or a Telegram chat / one-time web link that you started),
so the agent's own shell tool can never approve or advance anything.

## Features

| | Command | What it does |
|---|---|---|
| Stages | `op stage` | Discover → validate → build → operate → learn, with a document and pass checks per stage. Only you advance or step back (with a reason the agent reads) |
| Milestones | `op milestone` | Build stage work units that complete only when their test command exits 0; empty tests like `true` are refused |
| Metrics | `op metric` | Numbers for the learn stage, shown next to the success metric you set in discovery, plus automatic counts of sent and rejected items |
| Approval gate | `op guard` (PreToolUse hook) | Blocks outbound and irreversible commands, edits to the queue and stage files, and reading secrets. Applies to `cd project && …` and `git -C project …` too |
| Human-side sending | `op pending approve` | By default the approved action runs in your process at the moment you approve; the agent cannot send |
| Secrets | `op secret` | Tokens go in the macOS Keychain (every read asks you) or a 600-mode file outside the project; never printed, never in tickets |
| Real delivery | `op deliver` | X, Threads, email (SMTP) and webhooks (Slack/Discord) |
| X sign-in and refresh | `op connect x` | OAuth 2.0 with PKCE in your browser; expired tokens are refreshed and stored automatically |
| Remote approval | `op telegram`, `op serve` | Approve or reject from your phone with Telegram buttons (no open ports), or over your Wi-Fi with a one-time link |
| Resumable passes | `op pass` | A pass follows the stage's default steps with a step limit instead of "credits". Survives crashes and new sessions |
| Validation gate | `op verify` | Per type rules: posts (channel length), email (to/subject), research (≥3 source URLs), site (build must succeed) |
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
sh operator-skill/skills/operator/install.sh --print-hooks   # hook snippets for Claude Code / Codex / Cursor / Gemini CLI / Hermes
```

Without a hook the skill still works, but blocking becomes an instruction instead of a guarantee.

**2. Turn it on for one project**

```bash
alias op="$PWD/operator-skill/skills/operator/scripts/op"   # or put scripts/op on your PATH
mkdir ~/bakery-booking && cd ~/bakery-booking && op init    # a new idea starts at the discover stage
# already running a product?  op init --stage operate
```

**3. Talk to your agent** (open a new session in that folder)

> I want to build a booking page for small bakeries. Let's figure it out with operator.

The agent asks one question at a time and writes the answers into `.operator/stages/discover.md`
(problem, customer, offer, success metric). When `op stage check` passes it asks you to move on.

**4. Move stages and approve things — yourself**

```bash
op stage                 # where you are and what is left
op stage advance         # discover → validate → build → operate → learn, after the checks pass
op pending list
op pending approve 0001  # sends right away from this terminal; or: op pending reject 0001 --reason "too stiff"
```

**5. Connect channels when you reach the operate stage**

```bash
op secret set OPERATOR_WEBHOOK_URL   # start with a private Discord/Slack webhook to see the whole loop
op connect x                         # then X (see channels guide), Threads, email
op telegram                          # optional: approve from your phone
```

## Using it in Hermes (a dedicated business assistant)

With [Hermes Agent](https://github.com/NousResearch/hermes-agent) as the engine you use operator from an app and from
messengers, without a terminal. Hermes itself is not modified: operator adds a plugin, the skill and a personality (SOUL.md).
Checked against Hermes 0.22.5.

```bash
git clone https://github.com/pullyo/operator-skill
sh operator-skill/hermes/operator/install.sh      # creates the 'operator' profile with the plugin, skill and personality
# to turn your existing default Hermes into Operator instead: add --home ~/.hermes
operator setup                                    # guided setup (Korean)
```

`operator setup` walks through six steps: model login (handing off to Hermes' model setup when needed), enabling the plugin,
the project folder, the approval mode (desktop + messenger, or messenger only), the messenger and its allowed user for phone
approvals, and a second lock (a shell hook that blocks even if the plugin is off). `operator setup --hermes` opens the original
Hermes wizard; `operator setup model` runs one Hermes section.

In the chat (Desktop, or a connected Telegram etc.): `/idea <one line>`, `/project`, `/stage`, `/advance`, `/back <stage> <reason>`,
`/inbox`, `/ok <id>`, `/reject <id> <reason>`, `/setup`. Hermes' built-in `/approve` is for dangerous-command prompts and is not
operator's `/ok`. Projects made with `/idea` refuse terminal approvals; to accept only commands typed in a messenger, set
`"human_via": ["messenger"]` in `.operator/guard.json`. Design, and what is and is not verified: [docs/hermes-design.md](docs/hermes-design.md).

## Commands

| Command | Who | Purpose |
|---|---|---|
| `op init [--stage S] [--send human\|agent]` · `op status` | anyone | Create the workspace; show stage, pass, queue and rejections |
| `op stage` · `doc` · `check` · `history` | agent | See the stage, create its document, check the exit conditions |
| `op stage advance` · `back --to S --reason …` · `set S` | **you**, interactive terminal | Move the project between stages |
| `op milestone add "title" --test "cmd"` · `done N` · `list` | agent | Build stage milestones, completed only by a passing test |
| `op metric add NAME VALUE [--source …]` · `list` | agent / you | Record numbers for the learn stage |
| `op pass start/next/done/fail/end` | agent | Run and checkpoint a pass |
| `op verify <file> --type …` | agent | Check a draft before queueing |
| `op pending add <file> [--action "cmd"]` | agent | Validate and queue a draft (x/threads/email/webhook get `op deliver <id>` automatically) |
| `op pending list/show` | anyone | Read the queue |
| `op pending approve <id> [--action "cmd"] [--no-send]` · `reject <id> --reason …` | **you**, interactive terminal | Decide; in human send mode, approving sends |
| `op send <id>` | agent (agent mode) / you | Run the approved action, nothing else |
| `op secret set/rm NAME` · `list` | **you** / anyone | Store tokens (Keychain or 600 file); list names only |
| `op connect x` | **you** | Sign in to X in the browser; tokens refresh automatically |
| `op telegram [--setup]` · `op serve [--lan]` · `op notify` | **you** / agent | Phone approval over Telegram or Wi-Fi · push the number of waiting items |
| `op feedback` | agent | Read recent rejection reasons |
| `op deliver --check` | anyone | Show which channels are ready (never prints values) |
| `op guard check [--cwd DIR] "cmd"` | anyone | Would this command be blocked? |
| `op llm --role summarize …` | agent | Route a narrow task to a local model |

## Safety model

**Enforced** (by the hook and by `op` itself):

- Outbound and irreversible commands are blocked: social API posts, mail, `curl` POST/PUT/DELETE to remote hosts, `git push`
  (including `git -C … push`), `vercel/netlify/wrangler/fly deploy`, `npm publish`, Stripe charges, domain purchases,
  recursive deletes, `git push --force`, `DROP TABLE`.
- The queue (`.operator/pending|approved|sent|rejected`) and the stage, milestone, metric and guard files change only through `op`.
  Writing to them with an edit tool or with `mv`/`cp`/`>`/`sed -i`/a Python one-liner is blocked. Reads are allowed.
- Approving, rejecting, moving stages, storing secrets, connecting accounts and starting the approval servers need a human
  decision route (an *authority*): an interactive terminal on the CLI, or the Hermes plugin receiving a command you typed
  (`/approve`). The route is recorded on the ticket (`decided_by`) and in the stage history (`by`). No environment variable
  turns an agent into a human.
- In the default human send mode, the agent cannot run `op send` at all; the approved action runs in your process.
  In agent mode, `op send` runs only the action recorded on the approved ticket.
- Reading `~/.config/operator/`, `security find-generic-password`, `printenv` and the like are blocked, including through the
  Read tool. Keychain items are stored so that every read asks you.
- A stage only advances when its checks pass; a milestone only completes when its test command exits 0.
- Domain purchases and payments are never queued: you do those yourself.

**Not covered** — be aware:

- **The terminal check is accident protection, not proof.** An agent's shell tool has no terminal, so ordinary calls fail,
  but a fake terminal (`script -q /dev/null op …`) or a command hidden in a script file can get past the TTY check and the
  guard (confirmed on macOS). To stop a determined agent running as your user, accept only the Hermes messenger route with
  `"human_via": ["messenger"]` in `.operator/guard.json`, and use isolation tier 2 (docker) for real deploy accounts
  ([docs/hermes-design.md](docs/hermes-design.md), section 4).
- Tools without hooks only get the rules as instructions. The Keychain prompt and human send mode still keep tokens away from them.
- The guard reads commands; paths built from variables (`cd $HOME/x`) are judged from the session folder only, and the guard only
  acts on calls that reach a folder with `.operator/`.
- The agent chooses its milestone test commands; you see them when you advance from the build stage, so read them.
- Telegram cards include the draft text, which passes through Telegram's servers (`--titles-only` avoids that).
  `op serve --lan` is plain HTTP on your local network.

## Limits

- operator does not run by itself. Each pass starts when you (or your OS scheduler) ask for it —
  see [scheduling](skills/operator/references/scheduling.md). Sending in human mode needs your computer on.
- It does not design your brand, buy domains or take payments.
- X, Threads, SMTP and Telegram are tested against local fakes of their APIs, not live accounts. Threads tokens are not refreshed.

## Repository layout

```
operator-skill/
├── .claude-plugin/        Claude Code plugin + marketplace manifest
├── .codex-plugin/         Codex plugin manifest
├── hooks/hooks.json       Claude Code plugin hook (approval gate)
├── hermes/operator/       Hermes plugin (slash commands, guard hook, SOUL.md, install.sh)
├── docs/                  Design notes (hermes-design.md)
├── tests/                 End-to-end tests that drive the real `op` process
└── skills/operator/       The skill (Agent Skills format)
    ├── SKILL.md           What the agent reads
    ├── scripts/op.py      The CLI — Python 3.8+, standard library only
    ├── references/        Stages, pass flow, guard / validation rules, channels and secrets, scheduling, design notes
    ├── assets/            Draft templates, per-tool hook snippets, launchd template
    └── install.sh         Multi-tool installer
```

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests feed the same hook JSON that Claude Code and Codex send into the real `op` process, walk a project through every
stage, and post to local fake X, Threads, token and Telegram endpoints with a temporary home folder, so no real account or
keychain is touched.

## Background

The design was inspired by how [Foundable](https://foundable.com) describes its AI employee publicly
(build → run → earn, everything waiting for your OK). operator is an independent implementation and is not affiliated with
Foundable. Design notes: [references/foundable-research.md](skills/operator/references/foundable-research.md).

## License

MIT
