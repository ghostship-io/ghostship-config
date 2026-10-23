# Policy enforcement

This map covers the independent T3 recovery controller.

| Recovery rule | Enforcement |
| --- | --- |
| 30-second sampling, 300-second known downtime, 600-second healthy rearm, three launches per rolling day | Controller constants and persistent episode state; `tests/test_t3code_recovery.py` |
| Healthy or unknown state, active tasks, maintenance and deployment gates prohibit ineligible remedies | Controller eligibility and final rechecks; controller tests |
| Durable attempt recorded before advice or mutation; fixed operations only | Controller ledger and fixed argv; controller tests |
| Owner automation authority recorded for eligible remedies | `owner_approval` in rendered configuration and controller ledger; `tests/t3code-recovery.nix` and controller tests |
| Advisor 480 seconds; controller 1200 seconds; both one CPU, 1 GiB, 256 tasks | Systemd cgroups and execution lifetime; `tests/t3code-recovery.nix` |
| Advisor UID 3000, no capabilities, protected host filesystem and process view | Systemd service hardening; `tests/t3code-recovery.nix`; actual host sandbox remains a deployment gate |
| Only one live credential file, read-only and never copied; fresh private regular single-link source with no symlink components | Separate root source preflight, bound-inode comparison, closed refresh endpoint; `tests/test_t3code_recovery_units.py`; live pinned-client gate |
| No inherited credentials, configuration, MCP, skills, rules or tools | Fixed argv/environment, empty private home and filesystem isolation; advisor tests and live pinned-client gate |
| Diagnostics at most 64 KiB, proposal at most 16 KiB and schema-valid data | Bounded readers and schema validation in advisor and controller; advisor/controller tests |
| Activation preserves live T3 | Existing container restart guards plus rendered `restartIfChanged`/`stopIfChanged` checks; deployment session guard |
| App/DB stall with live static HTTP never authorizes a restart | Authenticated session probe, eligibility guard, host mutator guard and controller regression tests |
| Proxy repair requires authenticated native app health | Eligibility guard and controller regression tests |
| Required checks remain registered | `scripts/check-unit.py` includes controller/advisor tests; `scripts/check-integration` includes rendered Nix policy |

Run `nix develop .#ci -c scripts/check` after staging new Nix files. A failed
check blocks completion. Never exercise recovery against shared services to prove
a test: controller tests substitute all external operations. Live acceptance is
limited to an isolated advisor producing a proposal and inspecting its sandbox.
