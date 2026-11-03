# ATH on DeepSeek Harness — plugin skeleton and live run

ATH, short for Agentic Test Harness, is the Fortior-line plugin set for
industrial motor testing. It is not another harness: it is a set of plugins that
mount inside **DSH (DeepSeek Harness)**, DeepSeek's open-source agent runtime,
distributed on npm as `@deepseek-ai/dsh` and documented at
https://deepseek-harness.github.io/deepseek-harness/ with source at
https://github.com/deepseek-ai/deepseek-harness .

This repository is the skeleton: three MCP tool stubs, one skill, one blocking
hook, the overlay that mounts them, and the evidence that a DeepSeek model
actually drives them end to end.

**Status: working.** `deepseek-v4-pro` loads the skill, calls the motor and
oscilloscope tools in order, reaches a verdict, stops the motor, and is blocked
by the safety hook when asked for 30 A. The full transcript is in
[`logs/e2e.md`](logs/e2e.md).

---

## Contents

1. [Install](#1-install)
2. [Version locking, and the trap that wastes an afternoon](#2-version-locking-and-the-trap-that-wastes-an-afternoon)
3. [Directory structure](#3-directory-structure)
4. [Running it](#4-running-it)
5. [The three MCP stubs and their contracts](#5-the-three-mcp-stubs-and-their-contracts)
6. [The skill](#6-the-skill)
7. [The hooks, and why there are two bridges](#7-the-hooks-and-why-there-are-two-bridges)
8. [Contract deviations](#8-contract-deviations)
9. [Verification results](#9-verification-results)
10. [Ecosystem survey](#10-ecosystem-survey)
11. [Pitfalls](#11-pitfalls)
12. [Architecture notes carried over from the ecosystem survey](#12-architecture-notes-carried-over-from-the-ecosystem-survey)

---

## 1. Install

Node 24 and Python 3.10 or newer. Everything below was run on WSL2, Ubuntu,
kernel 6.18.

```sh
mkdir -p c/components/dsh-plugins && cd c/components/dsh-plugins

# DSH itself. Exactly one dependency. See section 2 before adding a second.
npm install --save-exact @deepseek-ai/dsh@0.1.5-rc.2

# Python side for the three MCP stubs.
uv venv .venv --python 3.10
UV_INDEX_URL=https://pypi.org/simple uv pip install --python .venv/bin/python mcp zstandard
```

The DeepSeek API key is read from the environment, never from a file in this
repository:

```sh
export DEEPSEEK_API_KEY=$(python3 -c \
  "import json;print(json.load(open('$HOME/.claude/settings.json'))['env']['DEEPSEEK_API_KEY'])")
```

The key used for the runs recorded here begins `sk-***`(已脱敏). DSH also stores keys
entered through its Settings page in `$DSH_HOME/.credentials.yaml`; the
environment variable takes precedence and is what these runs used.

Model availability was confirmed against the live API rather than assumed:

```sh
curl -s https://api.deepseek.com/models -H "Authorization: Bearer $DEEPSEEK_API_KEY"
# -> deepseek-flash, deepseek-v4-pro
```

`deepseek-v4-pro` is selected in `cordis.patch.yml`; the DSH web bundle's own
default is `deepseek-flash`.

---

## 2. Version locking, and the trap that wastes an afternoon

DSH is a developer preview and its own README says there will be
compatibility-breaking changes, so every version is pinned exactly, with no
caret or tilde. As of 2026-09-19 the npm dist-tags are:

| Tag | Version |
|---|---|
| `latest` | 0.1.5-rc.2 |
| `next` | 0.1.5-rc.2 |
| `alpha` | 0.1.6-alpha.2 |

This project locks **0.1.5-rc.2**.

**Do not install the sub-plugin packages at the top level.** The DSH plugin
packages — `@deepseek-ai/dsh-mcp-client`, `@deepseek-ai/dsh-skill`,
`@deepseek-ai/dsh-hooks-claude-code` and the rest — already ship inside
`@deepseek-ai/dsh`, in its own nested `node_modules`. Installing them again as
top-level dependencies makes npm hoist a second, older copy of the shared core
packages, and the harness then loads two different `@deepseek-ai/dsh-scope`
modules. Scope identity is carried by that module, so the two copies do not
recognise each other's scope keys and everything downstream breaks in ways that
look unrelated to the install:

```
# Web UI: every session creation fails
agent-presets: refusing to compose an unscoped context;
the scope key is what joins an agent to its preset

# headless: every tool call fails
UNKNOWN: Cannot read properties of undefined (reading 'prepare')
```

Diagnosis, when either message appears:

```sh
find node_modules -name package.json -path "*dsh-scope*" \
  -exec sh -c 'python3 -c "import json,sys;print(json.load(open(sys.argv[1]))[\"version\"], sys.argv[1])" "$1"' _ {} \;
```

Two lines means two copies, and the fix is to delete `node_modules` and
`package-lock.json` and reinstall with `@deepseek-ai/dsh` as the only dependency.
One line is correct. This project's `package.json` deliberately has exactly one
dependency for that reason.

Third-party plugins go in through DSH's own plugin manager, which installs into
the profile directory as a pnpm workspace and never touches the top level:

```sh
dsh plugin --profile web add <package>@<exact version>
```

---

## 3. Directory structure

```
c/components/dsh-plugins
├── package.json              one pinned dependency: @deepseek-ai/dsh 0.1.5-rc.2
├── cordis.patch.yml          the ATH overlay: MCP stubs, hooks, skill roots, model
├── README.md                 this file
│
├── mcp/                      three stdio MCP servers, Python, official `mcp` SDK
│   ├── _common.py            shared JSON-line logger
│   ├── motor_mcp.py          motor_start / motor_stop / motor_read_omega / motor_read_udc
│   ├── scope_mcp.py          rigol_connect / rigol_capture / rigol_measure
│   └── report_mcp.py         fill_report
│
├── skills/
│   └── coolingfan-startup-check.md    the startup-test procedure and acceptance criteria
│
├── hooks/
│   ├── hooks.json                     Claude Code dialect — the enforcing gate
│   ├── pretooluse_motor_current.py    exit 2 above 20 A
│   ├── hooks.codex.json               Codex dialect — evidence only
│   └── codex_payload_probe.py         records what the Codex bridge delivers
│
├── data/
│   └── faithful_norm1200.csv          real bench capture backing the scope stub
│
├── bin/python                needed by dsh-kb-rag; see section 10
├── logs/                     stub logs, hook audit, run stdout, e2e.md
├── reports/                  output of report_mcp.fill_report
├── shots/                    Web UI screenshots
│
├── tools_smoke_mcp.py        talk to the three stubs directly, no harness
├── tools_drive_ui.py         Playwright driver for the Web UI
├── tools_dump_session.py     print one session's tool-call timeline
└── tools_session_stats.py    per-session call counts and token totals
```

`data/faithful_norm1200.csv` is copied from
`测试数据_20260701/faithful_norm1200.csv`.

---

## 4. Running it

### Non-interactive, one task, prints the answer and exits

```sh
cd c/components/dsh-plugins
export DEEPSEEK_API_KEY=...
./node_modules/.bin/dsh --profile headless --patch ./cordis.patch.yml \
  "对散热风扇做一次起动测试并判定。调试器路径用 [源] bin/AsicCliDebugger.exe。"
```

### Web UI

```sh
./node_modules/.bin/dsh web --patch ./cordis.patch.yml --no-open --port 3080
```

The URL it prints carries a one-time trust token; open that exact URL, not a bare
`http://127.0.0.1:3080/`, which answers 401. Two first-run gates stand between a
fresh browser and a usable composer: an "Internal Testing Notice" modal, and a
workspace choice. `tools_drive_ui.py` drives both.

### Checking the stubs without the harness

```sh
.venv/bin/python tools_smoke_mcp.py
```

Talks to all three servers directly over stdio. If this passes and the model
still cannot reach a tool, the fault is in the overlay or the harness, not in
the server.

### Reading back what happened

```sh
.venv/bin/python tools_session_stats.py
.venv/bin/python tools_dump_session.py \
  [源] sessions/--home-zzz-lab-dsh-plugins--<session-id>/session.v3.jsonl.zstd
```

Sessions are zstd-compressed JSONL under `$DSH_HOME/sessions/`. Hook scripts
cannot read them — the bridge always reports `transcript_path` as null or empty —
so these two scripts are the only route to an exact call sequence.

---

## 5. The three MCP stubs and their contracts

All three speak MCP over stdio, are written against the official Python `mcp`
SDK, and are mounted one `@deepseek-ai/dsh-mcp-client` instance each. The model
sees them under DSH's server-qualified naming, `mcp__<serverName>__<rawName>` —
the same shape Claude Code and Codex use.

Every call appends a JSON line to `logs/<server>.log`, mirroring the production
`append_rust_log("INFO", "[VibeTesting-MCP][Motor] …")` convention in a
machine-readable form.

### motor-mcp — `serverName: motor`

Tool names, parameter names and return shapes are copied from the production
Rust implementation, not invented:

- `[源] tools/types.rs`
- `[源] tools/motor.rs`

| Tool | Parameters | Returns |
|---|---|---|
| `motor_start` | `debugger_exe` (string, required), `current_limit_a` (number, optional — ATH extension) | text `Motor started successfully` |
| `motor_stop` | `debugger_exe` (string, required) | text `Motor stopped successfully` |
| `motor_read_omega` | `debugger_exe` (string, required) | `{"omega_rpm": <float>}` |
| `motor_read_udc` | `debugger_exe` (string, required) | `{"udc_voltage": <float>}` |

`debugger_exe` is the absolute path to the ASIC CLI debugger executable, exactly
as the Rust `MotorDebuggerArgs` struct requires it on all four tools. The stub
holds a running flag and a nominal operating point near 12,480 rpm and 24 V;
nothing is actuated.

### scope-mcp — `serverName: scope`

Tool and parameter names follow `TOOL_RIGOL_CONNECT` and `TOOL_RIGOL_MEASURE`
in the same `types.rs`.

| Tool | Parameters | Returns |
|---|---|---|
| `rigol_connect` | `device_path` (string, optional VISA resource) | connection record |
| `rigol_capture` | `channels` (int list, optional), `window_s` (number, optional) | per-channel statistics plus a `derived` block |
| `rigol_measure` | `measurement_type` (string, required: FREQ/VMAX/VMIN/VPP/VAVG/VRMS), `channel` (int, default 1) | one value with its unit |

Channel map, from the bench signal definition: 1 phase current sense, 2 FG1
tacho, 3 FG2 tacho, 4 PWM1 drive.

**Every payload carries a `source` field, and it is load-bearing.**

`source: "faithful_norm1200.csv"` means the number was computed for real from
`data/faithful_norm1200.csv` — 1200 samples, t = −12.00 to +11.98 s, 20 ms
spacing. The amplitude statistics are honest.

`source: "stub"` means the number is fabricated. That record is decimated to
20 ms spacing, far below the FG pulse rate; a rising-edge count over the full
24 s window returns zero crossings on every channel, so no frequency and no RPM
can be recovered from it. Every rotational figure the server returns — FG
frequency, RPM, the FG1/FG2 ratio, the fault flag — is a placeholder for wiring
the agent loop. Replace the file with a deep-storage capture before any of it is
reported as a measurement.

### report-mcp — `serverName: report`

| Tool | Parameters | Returns |
|---|---|---|
| `fill_report` | `template` (string, required), `images` (string list), `csv` (string), `verdict` (string), `notes` (string) | `{"output_path": …, "template": …, "embedded_images": <int>, "csv": …, "verdict": …, "source": "stub"}` |

The production report is a macro-enabled Excel workbook (`.xlsm`). This stub
writes a small JSON manifest under `reports/` and returns its path; the file it
names really exists after the call.

---

## 6. The skill

`skills/coolingfan-startup-check.md`, discovered by
`@deepseek-ai/dsh-skill-filesystem` through the `customSkillDirs` root set in the
overlay. Frontmatter carries the three fields that provider requires or accepts:
`name` (kebab-case), `description`, `whenToUse`.

The body states three acceptance criteria — FG2 above 10,000 rpm with no fault
flag; FG1/FG2 equal to 2.00 within ±0.05, which follows from the fan's 2 pole
pairs; and a commanded stop before the test is reported — then a six-step
procedure, then a section telling the model to read the `source` field on every
scope payload and to report a `stub`-decided verdict as a wiring rehearsal rather
than a measurement.

That last section is what made runs 1 and 3 refuse to declare a pass. It is worth
keeping when this skill is adapted.

---

## 7. The hooks, and why there are two bridges

DSH has no hook format of its own. It runs an existing hook config through a
compatibility bridge, and ships two: `@deepseek-ai/dsh-hooks-codex` and
`@deepseek-ai/dsh-hooks-claude-code`. Both read a `hooks.json`, support
`PreToolUse` and `PostToolUse` among others, and treat **exit code 2 as a block**
whose stderr becomes the model-visible reason. Any other exit code is a
non-blocking failure.

The original plan was the Codex bridge. It does not work for this gate, and the
reason is worth recording rather than rediscovering:

> A tool call's payload carries the real `tool_name` and the
> `tool_input: { command }` shape (the `command` argument when present, else
> `''`), so non-shell tool arguments are not faithfully exposed.
> — `@deepseek-ai/dsh-hooks-codex` README, "Payloads and environment"

A gate on `current_limit_a` needs to see `current_limit_a`. The Codex bridge
flattens it away. The Claude Code bridge passes the arguments through intact
(`tool_input: exec.arguments` in its `lib/index.js`), so that is the enforcing
path.

Both are mounted. The Claude Code bridge enforces; the Codex bridge runs a
non-blocking probe that writes the payload it received to
`logs/hook-codex-probe.log`, so the difference is documented by observation
rather than by quotation. Here is what it recorded during run 1:

```json
{"session_id":"session-780f4667-…","transcript_path":null,
 "cwd":"c/components/dsh-plugins","hook_event_name":"PreToolUse",
 "model":"deepseek-v4-pro","permission_mode":"default","turn_id":"1",
 "tool_name":"mcp__motor__motor_start","tool_input":{"command":""},
 "tool_use_id":"call_00_Y6YZxcRnHQfixztV0Ez17813"}
```

`tool_input` is `{"command": ""}`. The commanded current is nowhere in it.

### The gate itself

`hooks/pretooluse_motor_current.py`, matched on the tool name
`mcp__motor__motor_start`. It reads the payload on stdin, and when
`tool_input.current_limit_a` exceeds 20 A it prints the reason to stderr and
exits 2. Below the limit, absent, or non-numeric, it exits 0. Every decision is
appended to `logs/hook.log`.

Matcher note: under the Claude Code dialect a pattern matching
`^[A-Za-z0-9_|]+$` is treated as literal pipe-separated alternation rather than
as a regex. `mcp__motor__motor_start` is inside that character set, so it matches
literally.

Ordering note: hooks on one event run serially in config order, and a block ends
the chain. In run 2 the Claude Code bridge blocked first and the Codex probe
never ran.

---

## 8. Contract deviations

Two, both deliberate, both visible in the code.

**`motor_start` accepts `current_limit_a`.** The Rust handler takes only
`debugger_exe`. The optional number was added so the `PreToolUse` gate has an
argument to inspect; the task specifies a current-based block and the production
contract offers no current parameter to block on. When the real bridge replaces
this stub, either the Rust side gains the parameter or the gate must move to
whatever tool actually carries the current setpoint.

**`rigol_capture` does not exist in the Rust contract.** `types.rs` has
`rigol_screenshot` and `rigol_analyze_waveform`; `rigol_capture` was specified
for this skeleton and is implemented as a window-statistics call over the CSV.
`rigol_connect` and `rigol_measure` keep their production names and parameters.

---

## 9. Verification results

Full transcripts, call-by-call, in [`logs/e2e.md`](logs/e2e.md). Summary:

| Check | Result |
|---|---|
| `dsh --version` | 0.1.5-rc.2 |
| Model reachable | yes, `deepseek-v4-pro`, headless "你好" answered |
| Three MCP servers list and answer over stdio | yes, `tools_smoke_mcp.py`, 8 calls, all served |
| Model loads the skill | yes, `skill` tool, all four DSH runs |
| Startup-test chain, headless | `skill` → `motor_start` → `rigol_capture` → `rigol_measure`×2 → `motor_read_udc` → `motor_stop` |
| Startup-test chain, Web UI | `skill` → `motor_start` → `rigol_capture` → `motor_read_omega` → `motor_stop` |
| `fill_report` called by the model | no — the model asked for the template and CSV first, which the skill permits |
| Hook blocks at 30 A | yes, `decision=block exitCode=2`, `logs/motor.log` stayed empty |
| Hook passes below the limit | yes, `decision=pass exitCode=0` |
| Web UI screenshots | `shots/ui-*.png` |

Token cost on `deepseek-v4-pro`, from the session logs: one startup-test turn is
**0.2–0.3 M total tokens**, of which 85% or more is cache read. The Web UI turn
costs about 40% more than the headless one, because the web profile mounts shell
and filesystem tools that widen the schema block and invite exploratory calls.

---

## 10. Ecosystem survey

Directories surveyed: dsh-plugin.org, dsh.pub, dshfind.com, the GitHub topic
`dsh-plugin`, and the npm registry.

**Hardware and instrument plugins: zero hits.** Searches for oscilloscope, motor,
Modbus, SCPI and instrument turned up nothing DSH-specific. The closest match is
`dsh-serial` 0.1.0, a UART/COM debugging console for firmware work, not an
instrument-control bridge. The three directory sites have no hardware or
industrial category at all. Building our own MCP servers is therefore the only
path, and keeping them as standard MCP servers — rather than native DSH
TypeScript plugins — keeps them reusable outside DSH.

One correction to the names that were circulating: none of the community plugins
below live under the official `@deepseek-ai` npm scope. They are bare-name
third-party packages, and `dsh-ssh-ops` in particular is
`caoyiwei850/dsh-ssh-ops`, not DeepSeek-maintained.

| Category | Package | Latest | Repository |
|---|---|---|---|
| Knowledge base / RAG | `dsh-kb-rag` | 1.6.7 | github.com/Breeze136/dsh-kb-rag |
| Knowledge base / memory | `dsh-knowledge-sqlite` | 0.1.9 | github.com/NinjaSln-labs/dsh-knowledge-sqlite |
| SSH remote | `dsh-ssh` | 0.3.0-pre | github.com/UynajGI/dsh-ssh |
| SSH ops + DB panel | `dsh-ssh-ops` | 0.3.11 | github.com/caoyiwei850/dsh-ssh-ops |
| Charts | `dsh-chart` | 0.5.0 | not declared in npm metadata |
| Charts (ECharts) | `@sparkelf/dsh-chart` | 0.1.2 | github.com/SparkElf/dsh-plugins-plus |
| Voice | `dsh-voice-scribe` | 0.4.9 | github.com/PensiveFei/dsh-voice-scribe |
| Document parsing | `dsh-markitdown` | 0.1.2 | github.com/jiekesu967/dsh-markitdown |
| Document parsing (MinerU) | `dsh-pdf-mineru` | 0.0.15 | github.com/Yurzi/dsh-pdf-mineru |

`dsh-ssh` is the one to look at first for the Fortior bench: it implements DSH's
`ctx.subprocess` and `ctx.fs` seams over SSH, so every tool built on those seams
switches to the remote host with no changes — which is a cleaner route to the
bench machine at 172.25.5.166 than tunnelling each tool individually.

### Trial install: `dsh-kb-rag` 1.6.7

```sh
dsh plugin --profile web add dsh-kb-rag@1.6.7
dsh plugin --profile headless add dsh-kb-rag@1.6.7
```

It installs into the profile as a pnpm workspace dependency and appends itself to
`dsh.profile.bundles`; `--dump-config` then shows `- id: kb-rag / name: dsh-kb-rag`
as a bundle layer, ahead of the `--patch` overlay. It loads and registers cleanly:

```
[kb-rag] static tools registered (v1.6.7): kb_ingest / kb_search / kb_rag /
         kb_zotero / kb_dedup / kb_clear / kb_fetch / kb_scope / kb_stats / kb_status
[kb-rag] ready (v1.6.7): 10 tools + /kb command
```

It does not run out of the box. Three things had to be fixed, and all three were
reported by the plugin itself with an exact remedy rather than as a crash:

1. **It spawns the bare name `python`, and this machine has only `python3`.**
   A shim at `bin/python` with that directory on `PATH` fixes it — but the shim
   must be a wrapper script, not a symlink. `.venv/bin/python` is itself a
   symlink to the system interpreter, so a symlink to it makes Python look for
   `pyvenv.cfg` beside the shim, find none, and fall back to `sys.prefix=/usr`,
   losing every package in the venv. `bin/python` is therefore two lines of
   `sh` that `exec` the venv interpreter by its real path.
2. **`faiss-cpu` and `sentence-transformers` were missing.** Installing them
   naively pulls the CUDA build of torch — `nvidia-cudnn-cu13` at 527 MB,
   `nvidia-cufft` at 204 MB — and the download times out. Use the PyTorch CPU
   index:
   ```sh
   UV_HTTP_TIMEOUT=300 uv pip install --python .venv/bin/python \
     --extra-index-url https://download.pytorch.org/whl/cpu \
     --index-strategy unsafe-best-match torch faiss-cpu sentence-transformers
   ```
   Installed here: torch 2.14.0+cpu, faiss-cpu 1.15.1, sentence-transformers 6.1.0.
3. **`pymupdf` was missing**, reported on the next run. `uv pip install pymupdf`.

After those three, the dependency check passes and the tools answer:

```
[kb-rag] Python dependencies OK
kb_stats -> 知识库统计 · 0 文档 / 0 块 / 0 向量
           数据库：[源] .kb/kb.sqlite
```

After those three, the dependency check passes and the plugin serves real data:

```
[kb-rag] Python dependencies OK
kb_stats -> 知识库统计 · 0 文档 / 0 块 / 0 向量
           数据库：[源] .kb/kb.sqlite
```

`kb_ingest` on this project's own `README.md` and `logs/e2e.md` completed —
`.kb/kb.sqlite` holds 2 documents and 42 chunks, confirmed by reading the table
directly. Retrieval works too, with correct section-level provenance. Calling
the engine by hand:

```sh
echo '{"query":"hook exit code 2 block","top_k":2,"kb_root":"'$PWD'/.kb"}' \
  | ./bin/python [源] dsh-kb-rag/kb_engine.py search
```

returns section "7. The hooks, and why there are two bridges", paragraphs 76–82,
with the right snippet, in **3 seconds** on CPU.

**Verdict: the engine works; the plugin's DSH-side daemon does not, here.** Every
`kb_search` issued by the model failed:

```
Error: kb engine daemon timed out
[kb-rag] scope question failed: Error: cannot get property "timeout" without inject
```

The second line is a plugin defect, not a configuration problem: `dsh-kb-rag`
reaches for a `timeout` service it never declared in its `inject` list, which the
Cordis scope refuses. So the retrieval quality is proven and the integration is
not. For a knowledge-base plugin on this DSH version, budget time for that
daemon path or call `kb_engine.py` directly from an MCP wrapper of your own.

`kb_stats` and `kb_ingest` go through a different path and both work.

---

## 11. Pitfalls

**The duplicate `dsh-scope` copy.** Covered in section 2. It cost the most time
of anything here, because both its symptoms — a Web UI that cannot create a
session, and a headless profile that cannot execute a tool — read as harness bugs
rather than as an install problem. Check for it first whenever DSH misbehaves in
a way the docs do not describe.

**Do not re-enable `dsh-skill-badge` outside the Web UI.** The web bundle ships
it disabled. Forcing it on in an overlay that is also used with `--profile
headless` crashes the run with `Cannot read properties of undefined (reading
'prepare')` — a different instance of the same unhelpful message. The overlay
re-enables `skill-filesystem` and `tool-skill` only, and says so in a comment.

**The Python MCP SDK renamed its server class.** `mcp` 2.x replaced `FastMCP`
with `MCPServer`; `from mcp.server.fastmcp import FastMCP` now raises at import
with a migration pointer. These stubs use
`from mcp.server.mcpserver import MCPServer`. Pin `mcp<2` only if you are porting
older code.

**The default PyPI mirror in this environment returns 403.** Every `uv pip
install` here sets `UV_INDEX_URL=https://pypi.org/simple` explicitly.

**`--dump-config` before `--patch` guesswork.** `dsh --profile web --patch
./cordis.patch.yml --dump-config` prints the composed tree with a comment above
each row naming the layer that last wrote it. It is faster than reasoning about
precedence and it boots nothing.

**The Web UI needs a real browser session, not curl.** The printed URL carries a
one-time trust token, a notice modal blocks the first click, and the composer
stays inert until a workspace is chosen through its own dropdown — clicking the
workspace in the sidebar is not enough, and on a fresh `$DSH_HOME` a directory
browser opens instead. `tools_drive_ui.py` handles all of it.

**Playwright and `networkid`.** The UI holds a websocket open, so
`wait_until="networkidle"` never fires. Use `domcontentloaded` plus a fixed wait.

---

## 12. Architecture notes carried over from the ecosystem survey

Three findings from
`[源] _调研/A-开源工具与DSH插件生态.md`
that shape what this skeleton should become. They are recorded here because they
contradict assumptions that are easy to carry in from the task book.

**Custom tool cards need a client plugin.** The built-in Web client does not
consume the `presentCall` and `presentResult` hooks that a native TypeScript tool
can define. A custom card has to be a client plugin registered into the
`tool.call.toolview` slot. Both methods must also be pure functions, because
session replay re-runs them — no I/O, no clock, no randomness inside them.

**`cordis.patch.yml` and `cordis.yml` sit at different layers.** A distributed
plugin ships its own `cordis.patch.yml` and declares it through `dsh.bundle` in
its `package.json`; that is the bundle layer. A local `cordis.yml` or
`cordis.patch.yml` passed with `--patch` is a development-time overlay applied
after every bundle. This project's file is the second kind, which is why it is
named in the `--patch` flag on every command above and why `--dump-config` shows
it as the last writer. The `dsh-kb-rag` install in section 10 is a clean example
of the first kind sitting underneath it.

**There is no hardware plugin to reuse.** Confirmed by the survey and repeated in
section 10. The three MCP stubs here are the self-built path, and holding them to
the standard MCP server shape — rather than turning them into native DSH
plugins — keeps them usable from any MCP client.
