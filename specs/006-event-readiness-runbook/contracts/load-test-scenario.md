# Contract: k6 Load Test Scenario

**Feature**: 006-event-readiness-runbook
**File**: `tests/load/k6-ctf-scenario.js`

## Scenario Steps (per Virtual User)

Each VU executes these steps in order. All steps must complete without a non-2xx/3xx response for the VU iteration to count as successful.

| Step | Method | Path | Description | Failure condition |
|------|--------|------|-------------|-------------------|
| 1 | GET | `{BASE_URL}/` | Load home / login page; extract CSRF nonce | Non-2xx response or missing nonce |
| 2 | POST | `{BASE_URL}/login` | Submit team credentials with CSRF nonce | Non-200/302 response or no session cookie set |
| 3 | GET | `{BASE_URL}/challenges` | Fetch challenge list (authenticated) | Non-2xx or redirect to login |
| 4 | POST | `{BASE_URL}/api/v1/challenges/{CHALLENGE_ID}/attempt` | Submit wrong flag | Non-2xx response |
| 5 | POST | `{BASE_URL}/api/v1/challenges/{CHALLENGE_ID}/attempt` | Submit correct flag | Non-2xx response |
| 6 | POST | `{BASE_URL}/controller-proxy/activate` | Activate test challenge instance | Non-2xx response |
| 7 | GET | `{BASE_URL}/controller-proxy/status/999` | Check instance status | Non-2xx response |

## Thresholds

| Metric | Threshold | Spec reference |
|--------|-----------|----------------|
| `http_req_duration` | `p(95) < 2000` ms | SC-001 |
| `http_req_failed` | `rate < 0.01` (1%) | SC-001 |

## Options

```js
export const options = {
  vus: 50,
  duration: '5m',
  thresholds: {
    http_req_duration: ['p(95)<2000'],
    http_req_failed:   ['rate<0.01'],
  },
};
```

## Environment Variables (required at runtime)

| Variable | Example | Notes |
|----------|---------|-------|
| `K6_CTF_BASE_URL` | `https://ctfd.infodays.net` | No trailing slash |
| `K6_CTF_USERNAME` | `team-999` | Test team username |
| `K6_CTF_PASSWORD` | `<secret>` | Test team password |
| `K6_CTF_CHALLENGE_ID` | `1` | CTFd numeric challenge ID for test-web-1 |

## Run Command

```bash
k6 run \
  --out json=tests/load/results/run-$(date +%Y%m%d-%H%M%S).json \
  tests/load/k6-ctf-scenario.js
```

## Pass/Fail Semantics

- k6 exits 0 if all thresholds pass.
- k6 exits non-zero if any threshold fails.
- CI/CD pipelines or manual runs can use the exit code as the gate.
