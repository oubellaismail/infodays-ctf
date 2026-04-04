import http from 'k6/http';
import { check, sleep } from 'k6';

// Load test configuration
// 4 VUs per team account — simulates 4 team members browsing simultaneously.
// 50 teams × 4 members = 200 VUs total (Phase 7: 50-team scaling with ProxySQL).
export const options = {
  vus: 200,
  duration: '45m',
  thresholds: {
    http_req_duration: ['p(95)<3000'],  // p95 response time < 3000ms
    http_req_failed:   ['rate<0.01'],   // error rate < 1%
  },
};

// Environment variables (read at startup)
const BASE_URL            = __ENV.K6_CTF_BASE_URL           || 'https://ctfd.infodays.net';
const CHALLENGE_ID        = parseInt(__ENV.K6_CTF_CHALLENGE_ID || '1', 10);
const MANIFEST_CHALLENGE  = __ENV.K6_CTF_MANIFEST_CHALLENGE  || 'web-sqli';

// Team credentials — loaded from K6_CTF_TEAMS as JSON array, or single account fallback.
// Format: '[{"username":"Alpha Squad","password":"AlphaPass123","team_id":"1"},...]'
// team_id must match the CTFd numeric team ID so activate/status use correct K8s deployments.
// Each VU picks a team by index so concurrent VUs use different accounts.
let TEAMS;
if (__ENV.K6_CTF_TEAMS) {
  TEAMS = JSON.parse(__ENV.K6_CTF_TEAMS);
} else if (__ENV.K6_CTF_USERNAME && __ENV.K6_CTF_PASSWORD) {
  TEAMS = [{
    username: __ENV.K6_CTF_USERNAME,
    password: __ENV.K6_CTF_PASSWORD,
    team_id:  __ENV.K6_CTF_TEAM_ID || '1',
  }];
} else {
  throw new Error('Set K6_CTF_TEAMS (JSON array) or K6_CTF_USERNAME + K6_CTF_PASSWORD');
}

// Per-VU state: set once on first iteration, reused for all subsequent ones.
// k6 VU contexts are isolated — this is private to each VU.
let vuCsrfNonce     = null;
let vuLoggedIn      = false;
let vuSessionCookie = null;  // Raw cookie value, re-injected each iteration

// Persist the session cookie into the k6 VU cookie jar with a far-future expiry.
// CTFd sets session-only cookies (no Max-Age); k6 clears those at iteration
// boundaries. Re-injecting before every request keeps the session alive.
function persistSessionCookie() {
  if (!vuSessionCookie) return;
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000);
  http.cookieJar().set(BASE_URL, 'session', vuSessionCookie, {
    path: '/',
    expires: tomorrow.toUTCString(),
  });
}

// Login once per VU and store session + CSRF nonce for all subsequent iterations.
function ensureLoggedIn(team) {
  if (vuLoggedIn) return;

  // Stagger initial VU startup: spread 50 teams over 50 seconds (1s per team).
  // Simulates teams trickling in at event start rather than all logging in simultaneously.
  // 4 VUs per team share the same stagger so they log in together as a team.
  if (vuSessionCookie === null) {
    sleep(Math.floor((__VU - 1) / 4) * 1.0);
  }

  // GET login page to extract the form CSRF nonce
  const loginPageRes = http.get(`${BASE_URL}/login`);
  check(loginPageRes, { 'home page loads (200)': (r) => r.status === 200 });

  const nonceMatch = loginPageRes.body.match(/<input[^>]*name="nonce"[^>]*value="([^"]+)"/);
  vuCsrfNonce = nonceMatch ? nonceMatch[1] : '';

  // POST /login — 429 can occur if IP rate limiter triggers during initial burst;
  // treat it as non-failure so the error-rate threshold reflects infra issues only.
  const loginRes = http.post(`${BASE_URL}/login`, {
    name: team.username,
    password: team.password,
    nonce: vuCsrfNonce,
  }, {
    responseCallback: http.expectedStatuses({ min: 200, max: 399 }, 429),
  });
  const loginOk = check(loginRes, {
    'login succeeds (200/302)': (r) => r.status === 200 || r.status === 302,
  });

  // Refresh nonce from the post-login page (window.init.csrfNonce) for API calls
  const nonceMatch2 = loginRes.body.match(/csrfNonce['":\s]+['"]([a-f0-9]+)['"]/);
  if (nonceMatch2) {
    vuCsrfNonce = nonceMatch2[1];
  }

  if (loginOk) {
    vuLoggedIn = true;
    // Capture the raw session cookie value to re-inject each iteration
    const cookies = http.cookieJar().cookiesForURL(BASE_URL);
    vuSessionCookie = (cookies['session'] && cookies['session'].length > 0)
      ? cookies['session'][0]
      : null;
    persistSessionCookie();
  }
}

// Main test function — executes once per VU iteration.
// Login happens only on the first call; subsequent calls go straight to the scenario.
export default function () {
  // 4 VUs share the same team account (simulates 4 members per team)
  const team = TEAMS[Math.floor((__VU - 1) / 4) % TEAMS.length];

  // Re-inject session cookie BEFORE any request (k6 clears session cookies each iteration)
  persistSessionCookie();

  // Login once per VU lifecycle
  ensureLoggedIn(team);
  if (!vuLoggedIn) {
    sleep(1);
    return;
  }

  // CTFd API requests require the CSRF-Token header
  const apiHeaders = {
    'Content-Type': 'application/json',
    'CSRF-Token': vuCsrfNonce,
  };

  // Flag submission params — CTFd rate-limits rapid attempts (429) under load.
  // 429 is expected behavior for aggressive test pacing; mark it as non-failure
  // so the error-rate threshold reflects real infrastructure failures only.
  const flagParams = {
    headers: apiHeaders,
    responseCallback: http.expectedStatuses({ min: 200, max: 299 }, 429),
  };

  // Step 1: GET /challenges (authenticated browsing — the primary event-time action)
  const challengesRes = http.get(`${BASE_URL}/challenges`);
  // If redirected to login, session was invalidated server-side — force re-login
  if (challengesRes.url && challengesRes.url.includes('/login')) {
    vuLoggedIn = false;
    vuSessionCookie = null;
    sleep(1);
    return;
  }
  check(challengesRes, {
    'challenges page loads (200)': (r) => r.status === 200,
  });

  // Step 2: Submit wrong flag attempt
  // CTFd 3.8+: challenge_id in the request body (not the URL), endpoint is /attempt
  const wrongFlagRes = http.post(
    `${BASE_URL}/api/v1/challenges/attempt`,
    JSON.stringify({ challenge_id: CHALLENGE_ID, submission: 'wrongflag' }),
    flagParams
  );
  check(wrongFlagRes, {
    'wrong flag attempt (200 or 429)': (r) => r.status === 200 || r.status === 429,
  });

  // Step 3: Submit correct-format flag attempt
  const correctFlagRes = http.post(
    `${BASE_URL}/api/v1/challenges/attempt`,
    JSON.stringify({ challenge_id: CHALLENGE_ID, submission: 'infodays{test}' }),
    flagParams
  );
  check(correctFlagRes, {
    'flag submission (200 or 429)': (r) => r.status === 200 || r.status === 429,
  });

  // Step 4: Activate challenge instance via CTFd proxy
  // team.team_id must match the CTFd numeric team ID (K8s deployment is named team-{id}-{challenge})
  // MANIFEST_CHALLENGE is the manifest challenge_id string (e.g. "web-sqli"), not the CTFd numeric ID
  const activateRes = http.post(
    `${BASE_URL}/controller-proxy/activate`,
    JSON.stringify({ team_id: String(team.team_id), challenge_id: MANIFEST_CHALLENGE }),
    { headers: apiHeaders }
  );
  check(activateRes, {
    'activate responds (2xx)': (r) => r.status >= 200 && r.status < 300,
  });

  // Step 5: Check instance status
  const statusRes = http.get(`${BASE_URL}/controller-proxy/status/${team.team_id}`);
  check(statusRes, {
    'status responds (2xx)': (r) => r.status >= 200 && r.status < 300,
  });

  // Think time: 2 seconds between iterations (realistic browsing pace)
  sleep(2);
}
