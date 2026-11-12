# 05 — Authentication and security audit

## HRIS authentication flow

1. The browser submits username/email and password to `POST /api/auth/login`.
2. The server resolves the user and verifies a PBKDF2 password hash using the stored salt/hash.
3. The server issues a session cookie; the session token is stored hashed in the database with user identity, CSRF token, and expiry.
4. The cookie is `HttpOnly`, `SameSite=Strict`, and `Secure` on Vercel. Browser code checks `GET /api/auth/session`; it does not authorize requests itself.
5. Authenticated mutations check request origin and session CSRF token. Logout revokes the server session and clears the cookie.
6. Role checks occur in the backend before dashboard/directory operations. Current directory allowlists are `hr_admin` and `system_admin`.

These controls are evidenced in [hris_server.py](../../../hris_server.py), [login.html](../../../login.html), and [README.md](../../../README.md). Session duration, exact password policy for ordinary account creation, and operational rotation procedures should be verified before real-user rollout.

## Demo access boundary

- Demo mode is controlled by `HRIS_DEMO_MODE`, constrained to Vercel Preview/Production environment context, and uses `HRIS_DEMO_SESSION_SECRET` with a minimum 32-byte requirement.
- Demo sessions are cryptographically signed and identified separately from normal HRIS users.
- Demo GET allowlist exposes only synthetic dashboard and employee records. Demo API handling is not a general authorization bypass.
- Employee create/update/delete explicitly requires a non-demo user plus privileged role; other demo writes are not exposed by the route dispatch.
- The synthetic-data path does not need `DATABASE_URL`; normal HR Admin login still uses database-backed auth.
- Variable presence/scope/value in Vercel was not inspected. Whether demo is enabled in a particular deployment is unknown.

## Authorization matrix observed

| Principal | Session endpoint | Demo mock reads | HR summary/directory read | Employee mutations | Helpdesk admin |
|---|---|---|---|---|---|
| Anonymous | Allowed | Only via configured demo session | No (401) | No (401) | Legacy client-only gate |
| Demo session | Allowed | Yes, synthetic only | Synthetic demo handlers | Explicitly denied | No trusted server role |
| `employee` / `manager` | Allowed | No, unless separately demo | Denied by current directory roles | Denied | No server-backed Helpdesk permission |
| `payroll_admin` | Allowed | No, unless separately demo | Denied by current directory roles | Denied | No server-backed Helpdesk permission |
| `hr_admin` / `system_admin` | Allowed | Normal HR data | Yes | Yes, with CSRF and audit handling | No shared Helpdesk permission currently |

The table describes current core HR APIs; it does not imply other modules are implemented.

## Findings and risk ranking

### High — Legacy Helpdesk access is client-side only

[admin-login.html](../../../admin-login.html) contains demo credentials and sets browser session/role state. [admin.html](../../../admin.html) checks that client-controlled state and writes ticket updates to `localStorage`. A visitor can inspect/modify the client state or directly edit local storage; this is not authentication or authorization. Keep these pages strictly as non-sensitive prototypes until replaced by shared server authentication and permission checks. Do not store real employee, ticket, or asset information there.

### High — No employee self-service ownership boundary

The schema has no verified user-to-employee mapping and no employee-scoped profile endpoint. Current directory APIs are deliberately restricted to HR/system admin. Adding employee-facing routes without an explicit identity-to-record mapping and server-side ownership checks could expose other employees’ information.

### Medium — Login hardening is incomplete for production

No login rate limiting, MFA/SSO, password reset/recovery workflow, or verified identity lifecycle was found. Add these before production use with real HR data, according to organizational policy.

### Medium — Prototype browser storage is untrusted and may persist data

Helpdesk objects are stored in browser `localStorage` and can persist across sessions. Values that are later interpolated into HTML should be treated as untrusted. Avoid HTML injection sinks or escape/construct DOM nodes; never use browser storage to authorize an operation.

### Medium — Vercel deployment/environment state is unverified

Repository configuration cannot establish whether Vercel Deployment Protection is active, which environment variables are set, which branch is Production, or whether Preview/Production databases are separated. Verify these in Vercel with authorized project access before enabling public access or entering sensitive data.

### Low/Medium — Security operations and audit coverage need definition

Employee mutations have audit rows, but broader security-event coverage, structured log retention, alerting, session revocation operations, backup/restore drills, and formal data retention were not evidenced.

## Positive controls observed

- Server-side session storage with hashed session tokens.
- PBKDF2 password hash verification.
- HTTP-only, strict same-site cookies and secure cookies on Vercel.
- CSRF checks and exact-origin validation on mutation paths.
- Role checks in backend, not just UI.
- Synthetic, in-code public demo data and explicit demo mutation denial.
- Parameterized SQL, validation, optimistic update conflict handling, and audit records for employee mutations.
- Vercel security headers include `nosniff`, frame denial, referrer policy, and restricted permissions policy.
- The admin-provisioning script checks expected database/branch identity before connecting/inserting.

## Security acceptance gates for future phases

1. Maintain negative tests for anonymous, employee, manager, payroll-admin, and demo principals on every sensitive route.
2. Verify Demo Mode with `DATABASE_URL` unset and confirm no real database access is attempted.
3. Keep sensitive operations 401/403 in demo and for unauthorized users; do not rely on hidden controls.
4. Replace client-only Helpdesk access before collecting non-public data.
5. Define approved roles, employee record ownership, Helpdesk permissions, retention, privacy, and recovery requirements before implementation.
6. Verify Vercel environment scoping and Deployment Protection independently; this audit did not change them.
