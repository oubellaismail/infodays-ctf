# Contract: setup-ctfd.sh

**Script**: `scripts/setup-ctfd.sh`
**Purpose**: Idempotent script that waits for CTFd to be ready and configures it via the CTFd admin API.

## Inputs

### Environment Variables (required)

| Variable | Description | Example |
|----------|-------------|---------|
| `CTFD_URL` | Base URL of the CTFd instance | `https://ctfd.infodays.net` |
| `CTFD_ADMIN_TOKEN` | CTFd admin API token | `ctfd_...` |

### Environment Variables (optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `CTFD_EVENT_NAME` | Event name displayed in CTFd | `InfoDays CTF` |
| `CTFD_FLAG_FORMAT` | Flag prefix format hint | `infodays{...}` |
| `CTFD_START_TIME` | Event start time (ISO 8601) | Not set (no countdown) |
| `CTFD_END_TIME` | Event end time (ISO 8601) | Not set (no hard stop) |
| `POLL_INTERVAL` | Seconds between readiness retries | `5` |
| `POLL_TIMEOUT` | Max seconds to wait for readiness | `300` |

## Behaviour

1. Polls `$CTFD_URL/healthcheck` every `$POLL_INTERVAL` seconds until HTTP 200 is returned or `$POLL_TIMEOUT` is exceeded.
2. If CTFd is not ready within timeout, exits with code 1 and prints an error message.
3. Configures via CTFd admin API:
   - Event name: `$CTFD_EVENT_NAME`
   - Team mode: `true`
   - Registration: `disabled`
   - Flag format description: `$CTFD_FLAG_FORMAT`
   - Start time / end time if provided
4. Each configuration step is idempotent — re-running the script produces no change if already configured.

## Outputs

### Stdout

```
Waiting for CTFd at https://ctfd.infodays.net/healthcheck...
CTFd ready (attempt 3/60).
Configuring event name: "InfoDays CTF"... OK
Configuring team mode: on... OK
Configuring registration: disabled... OK
Setup complete.
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Setup completed successfully |
| 1 | CTFd readiness timeout exceeded |
| 2 | API configuration step failed (HTTP error or unexpected response) |

## Example Usage

```bash
export CTFD_URL="https://ctfd.infodays.net"
export CTFD_ADMIN_TOKEN="ctfd_abc123"
bash scripts/setup-ctfd.sh
```
