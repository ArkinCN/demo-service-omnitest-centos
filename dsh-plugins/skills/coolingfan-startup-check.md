---
name: coolingfan-startup-check
description: Run and judge one cooling-fan startup test on the Fortior motor bench — command the start, read the FG2 tacho, check the FG1/FG2 ratio, declare pass or fail, and always stop the motor afterwards.
whenToUse: The user asks for a cooling-fan startup test, a 起动测试, a startup judgement, or asks whether a fan started correctly.
---

# Cooling-fan startup check

One startup test on the Fortior motor bench, start to verdict. Follow the steps in order.
Do not skip the stop step, whatever the verdict.

## Acceptance criteria

Three criteria. All three must hold for a pass.

| # | Criterion | Threshold |
|---|---|---|
| 1 | Startup reached | FG2 tacho speed above 10000 rpm, and no fault flag raised |
| 2 | Tacho consistency | FG1 speed divided by FG2 speed equals 2.00, tolerance ±0.05 |
| 3 | Clean shutdown | The motor is commanded to stop before the test is reported |

Criterion 2 follows from the bench wiring: the fan has 2 pole pairs, so FG1 carries
twice the pulse rate of FG2. A ratio outside the window means a tacho channel is
miswired or one of the two FG signals is being lost.

## Procedure

1. Start the motor. Call `mcp__motor__motor_start` with `debugger_exe` set to the
   bench debugger path. Pass `current_limit_a` only when the user names a current;
   the bench safety hook rejects anything above 20 A.
2. Let it reach speed, then read the tacho. Call `mcp__scope__rigol_capture` to get
   the channel statistics and the derived FG figures, or `mcp__scope__rigol_measure`
   for one specific quantity.
3. Read the DC bus with `mcp__motor__motor_read_udc` when the verdict is in doubt;
   a collapsed bus explains a failed startup.
4. Judge against the three criteria above. State each criterion, the number you
   measured, and whether it passed.
5. Stop the motor. Call `mcp__motor__motor_stop` with the same `debugger_exe`.
   This is unconditional — a failed test still ends with the motor stopped.
6. Write the report only if the user asked for one. Call `mcp__report__fill_report`
   with the template, the backing CSV path, and the verdict.

## Reporting the numbers honestly

Every payload from `mcp__scope__*` carries a `source` field. `faithful_norm1200.csv`
means the number was computed from the bench capture and can be quoted as measured.
`stub` means the value is a placeholder standing in for hardware that is not
connected. When a criterion is decided on a `stub` value, say so in the verdict —
report it as a wiring rehearsal, never as a measurement.
