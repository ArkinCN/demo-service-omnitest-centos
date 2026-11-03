# ATH on DeepSeek Harness — end-to-end run record

ATH (Agentic Test Harness) is the Fortior-line plugin set built on DSH (DeepSeek
Harness, DeepSeek's open-source agent runtime, npm `@deepseek-ai/dsh`). This file
records the four runs that prove the wiring, taken from the durable session logs
rather than from screen scraping.

| Item | Value |
|---|---|
| dsh version | `@deepseek-ai/dsh` 0.1.5-rc.2 (npm dist-tag `latest` on 2026-09-19) |
| Model | `deepseek-v4-pro`, provider route `deepseek-official` |
| API key | `env.DEEPSEEK_API_KEY` in `[源] .claude/settings.json`, prefix `sk-***`(已脱敏), read into the process environment; never written into any config file in this repository |
| Overlay | `[源] dsh-plugins/cordis.patch.yml`, applied with `--patch` |
| Workspace | `c/components/dsh-plugins` |
| Session logs | `$DSH_HOME/sessions/--home-zzz-lab-dsh-plugins--/<session-id>/session.v3.jsonl.zstd` |
| Date | 2026-09-19 |

Two helper scripts in the project root read those logs:
`tools_dump_session.py` prints one session's call timeline, and
`tools_session_stats.py` prints per-session call counts and token totals.

---

## Run 1 — startup test and verdict, headless

Session `session-780f4667-7423-41a9-bacc-ea6013e33eda`.

```sh
dsh --profile headless --patch ./cordis.patch.yml \
  "对散热风扇做一次起动测试并判定。调试器路径用 [源] bin/AsicCliDebugger.exe。"
```

### Tool-call sequence

| # | Tool | Arguments | Result |
|---|---|---|---|
| 1 | `skill` | `{"name": "coolingfan-startup-check"}` | skill body loaded |
| 2 | `mcp__motor__motor_start` | `{"debugger_exe": "[源] bin/AsicCliDebugger.exe"}` | `Motor started successfully` |
| 3 | `mcp__scope__rigol_capture` | `{}` | 1200 samples, per-channel statistics, derived FG block |
| 4 | `mcp__scope__rigol_measure` | `{"measurement_type": "FREQ", "channel": 2}` | `value: null`, `source: stub` |
| 5 | `mcp__scope__rigol_measure` | `{"measurement_type": "FREQ", "channel": 3}` | `value: 208.0`, `source: stub` |
| 6 | `mcp__motor__motor_read_udc` | `{"debugger_exe": "[源] bin/AsicCliDebugger.exe"}` | `{"udc_voltage": 23.912}` |
| 7 | `mcp__motor__motor_stop` | `{"debugger_exe": "[源] bin/AsicCliDebugger.exe"}` | `Motor stopped successfully` |

Both hook bridges fired on step 2 and both passed:

```
hook/invoked  dialect=claude-code  point=PreToolUse  matcher=mcp__motor__motor_start
hook/result   decision=pass  exitCode=0  durationMs=59.1
hook/invoked  dialect=codex        point=PreToolUse  matcher=mcp__motor__motor_start
hook/result   decision=pass  exitCode=0  durationMs=21.4
```

The model did not call `mcp__report__fill_report`; it asked for the template and
CSV path first, which the skill permits (step 6 of the procedure makes the report
conditional on the user asking for one).

### Final answer, abridged

The model declared criterion 3 (clean shutdown) passed, and refused to declare
criteria 1 and 2 either way, because the figures deciding them carry
`source: "stub"`:

> 准则 1、2 依赖的 FG1/FG2 转速、比值、故障标志全部来自 `derived` 字段，其 `source` 均为 **`stub`**（占位符，不是测量值）… **不能判为通过（PASS）。**… 按技能要求作为「接线演练（wiring rehearsal）」上报，而非真实测量。

That is the intended behaviour. The skill's "Reporting the numbers honestly"
section tells the model to treat a `stub` source as a rehearsal, and it did.

---

## Run 2 — hook block at 30 A, headless

Session `session-867af621-d50f-4888-880a-183ec99da337`.

```sh
dsh --profile headless --patch ./cordis.patch.yml \
  "用 30 A 起动散热风扇。调试器路径 [源] bin/AsicCliDebugger.exe，current_limit_a 传 30。"
```

| # | Tool | Arguments | Result |
|---|---|---|---|
| 1 | `skill` | `{"name": "coolingfan-startup-check"}` | skill body loaded |
| 2 | `mcp__motor__motor_start` | `{"debugger_exe": "…", "current_limit_a": 30}` | **blocked** |

```
hook/invoked  dialect=claude-code  point=PreToolUse  matcher=mcp__motor__motor_start
hook/result   decision=block  exitCode=2
              stderrSummary="Blocked by the bench safety gate: mcp__motor__motor_start
              was called with current_limit_a = 30.0 A, above the 20.0 A limit …"
```

`logs/motor.log` stayed empty for this run: the MCP server was never reached, so
the block is a real interception and not a post-hoc rejection. The Codex probe
hook did not fire either — bridges on one event run serially in config order, and
the Claude Code bridge is mounted first, so its block ends the chain.

The model surfaced the reason to the user, offered to re-run at 20 A or to have
the bench owner raise the limit, and explicitly refused to lower the current on
its own initiative.

---

## Run 3 — the same task through the Web UI

Session `session-75dbaa17-d7b3-488c-8c36-cd494196f256`. Server started with:

```sh
dsh web --patch ./cordis.patch.yml --no-open --port 3080
```

Driven by `tools_drive_ui.py` (Playwright over the Chrome build at
`[源] chrome-linux64/chrome`).
Screenshots in `shots/ui-*.png`.

14 calls. The web profile mounts the shell and filesystem tools that headless
does not, so the model spent its first nine calls orienting itself — `bash` to
list the workspace and look for `[源] bin/AsicCliDebugger.exe` (absent, as
expected on this machine), then `read` on the skill and the three MCP stub
sources. The ATH chain proper is calls 10 through 14:

| # | Tool | Result |
|---|---|---|
| 10 | `skill` `coolingfan-startup-check` | loaded |
| 11 | `mcp__motor__motor_start` | `Motor started successfully` (both hook bridges passed) |
| 12 | `mcp__scope__rigol_capture` | 1200 samples + derived block |
| 13 | `mcp__motor__motor_read_omega` | `{"omega_rpm": 12458.8}` |
| 14 | `mcp__motor__motor_stop` | `Motor stopped successfully` |

The UI's own meter for this turn read **1 turn, 8 steps, 140K tok, cache hit 86%**.
The model again marked the verdict a wiring rehearsal rather than a measurement.

---

## Run 4 — ecosystem plugin smoke test

Sessions `session-7214fd69-…` and `session-c4724711-…`. See README section
"Ecosystem survey" for what was installed and how far it got.

---

## Token cost

Read from the session logs, all on `deepseek-v4-pro`. `totalTokens` is the
billed total including cache reads; `cacheReadTokens` is the discounted part.

| Session | Purpose | Tool calls | input | output | reasoning | cache read | total |
|---|---|---|---|---|---|---|---|
| `1f9ef34e` | single `motor_read_udc` probe | 1 | 6,756 | 278 | 92 | 39,936 | 46,970 |
| `780f4667` | Run 1, startup test headless | 7 | 4,020 | 6,706 | 4,870 | 184,320 | 195,046 |
| `867af621` | Run 2, 30 A block | 2 | 8,342 | 2,340 | 1,544 | 65,280 | 75,962 |
| `75dbaa17` | Run 3, startup test in Web UI | 14 | 37,060 | 10,440 | 7,518 | 231,936 | 279,436 |
| `7214fd69` | `kb_stats`, before python shim | 1 | 31,860 | 100 | 44 | 1,536 | 33,496 |
| `c4724711` | `kb_stats`, after python shim | 1 | 23,306 | 310 | 0 | 43,776 | 67,392 |

Order of magnitude: **one startup-test turn costs 0.2–0.3 M tokens**, of which
85% or more is cache read. The Web UI turn costs about 40% more than the headless
one because the web profile's shell and filesystem tools widen the tool schema
block and invite exploratory calls.

---

## What this run does not prove

- No hardware was touched. All three MCP servers are stubs.
- Every rotational figure (FG frequency, RPM, FG1/FG2 ratio, fault flag) is a
  placeholder. Only the channel amplitude statistics are computed from the real
  capture `data/faithful_norm1200.csv`.
- `mcp__report__fill_report` was never exercised inside a DSH run, only in the
  direct MCP smoke test. `reports/` is empty after these four runs.
