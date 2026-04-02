# Implementation Plan: Event Readiness & Runbook

**Branch**: `006-event-readiness-runbook` | **Date**: 2026-03-26 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/006-event-readiness-runbook/spec.md`

## Summary

Deliver four operational artifacts that gate the event opening: a k6 load test script simulating 50 concurrent players for 5 minutes (p95 < 2s, error rate < 1%), a Bash MySQL backup script, a pre-event checklist, and an event-day operations runbook. No new infrastructure is provisioned — this phase wraps all prior phase deliverables in runnable verification tooling and documentation.

## Technical Context

**Language/Version**: Bash 5 (backup script), k6 JavaScript ESM (load test)
**Primary Dependencies**: k6 (load test runtime), kubectl + kubeconfig (backup + checklist), mysqldump (inside MySQL pod)
**Storage**: `backups/` (local host, SQL dumps), `tests/load/results/` (local host, JSON run summaries)
**Testing**: k6 self-validates via thresholds; checklist and runbook verified manually; backup script tested by running against live cluster
**Target Platform**: Linux/macOS (operator workstation), DOKS cluster (kubectl target)
**Project Type**: Operational tooling + documentation
**Performance Goals**: p95 HTTP response time < 2 seconds; request failure rate < 1% at 50 concurrent VUs over 5 minutes
**Constraints**: Must work with the existing DOKS cluster and CTFd deployment from Phases 1–5; no new infrastructure; no monitoring stack (v2 scope boundary)
**Scale/Scope**: 50 concurrent teams, 12-hour event, 20–50 team accounts

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|-----------|-------|--------|
| I. Flag Integrity | Load test uses test credentials only; no real flags are exposed or logged | ✅ Pass |
| II. Security-First Pod Isolation | No challenge pod security changes; load test is external-only | ✅ Pass |
| III. Pod Lifecycle Discipline | Backup and checklist are read-only ops; no Deployment changes | ✅ Pass |
| IV. DigitalOcean-Exclusive Infrastructure | No new cloud resources introduced; all tools run against existing DOKS cluster | ✅ Pass |
| V. Resource & Cost Discipline | No new workloads; k6 runs on operator workstation | ✅ Pass |
| v1 Scope Boundaries | No Prometheus/Grafana/Alertmanager; monitoring explicitly excluded from spec | ✅ Pass |
| Language & Tooling | k6 is the constitutionally mandated load test tool; Bash for scripts | ✅ Pass |

**Post-Phase 1 Re-check**: No violations introduced during design. All contracts are purely operational.

## Project Structure

### Documentation (this feature)

```text
specs/006-event-readiness-runbook/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── load-test-scenario.md
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
tests/
└── load/
    ├── k6-ctf-scenario.js     # Load test script (new)
    └── results/               # JSON run summaries (gitignored)

scripts/
├── backup-mysql.sh            # MySQL backup script (new)
└── [existing scripts unchanged]

docs/
├── pre-event-checklist.md     # Pre-event sign-off gate (new)
└── event-day-runbook.md       # Operations runbook (new)

backups/                       # SQL dumps (new dir, gitignored)
```

**Structure Decision**: Single-project layout extending the existing repository structure. No new top-level project or package needed. The `docs/` and `backups/` directories are new; `tests/load/` is a new subdirectory under the existing `tests/` tree.

## Complexity Tracking

> No constitution violations — table not required.
