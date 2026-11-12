# 07 — Vercel deployment audit

## Repository deployment configuration

[vercel.json](../../../vercel.json) configures the Python Function `api/index.py` and:

- Rewrites `/api/:path*` to `/api?__vercel_route=:path*`.
- Rewrites `/` to the API public-entry route.
- Rewrites `/employee-hub` and `/hris` to `/index.html`.
- Adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, and a restrictive `Permissions-Policy`.
- Excludes tests, scripts, migrations, bytecode, local database files, logs, README, and `.gitignore` from the Function bundle.

[api/index.py](../../../api/index.py) restores the path from Vercel’s rewrite query and subclasses `HRISHandler`. [hris_server.py](../../../hris_server.py) handles API requests and local static serving. Vercel’s static asset delivery and Function routing must both continue working when code is extracted.

## Public root and login routes

- Root `/` reaches `/api/public-entry`. With demo enabled, the server redirects to `/employee-hub#home`; otherwise it redirects to `/index.html`, whose frontend authentication flow routes unauthenticated users through the existing login.
- `/employee-hub` and `/hris` serve the shared `index.html` shell.
- The server’s local route behavior also maps these application paths.
- `/api/*` calls are forwarded through the Python Function adapter.

The repository does not configure Vercel Deployment Protection, project access policy, Git integration, production branch, aliases, or deployment domains.

## Runtime and dependency compatibility

- Python dependencies are listed in [requirements.txt](../../../requirements.txt); the current application requires `psycopg[binary]` and `python-dotenv`.
- `api/index.py` is the Vercel Python Function entry. `vercel.json` does not pin an explicit Python runtime version in the file reviewed; the effective runtime/build behavior must be confirmed against current Vercel platform settings.
- `hris_server.py` is imported by the Function adapter and therefore must remain bundle-accessible.
- The Function must not depend on writable local SQLite state for durable Vercel behavior. Vercel deployments require configured `DATABASE_URL` for normal HRIS database operations.
- Demo-only API access uses synthetic records and does not require the database; HR Admin login remains database-dependent.
- Migration files are excluded from the Function bundle, consistent with the manual migration process.

## Environment variable references

| Variable | Purpose indicated by source/docs | Environment value/status |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection for authenticated HRIS operations. | Not inspected; unknown. |
| `HRIS_DEMO_MODE` | Enables public demo mode only within supported Vercel environment context. | Not inspected; unknown. |
| `HRIS_DEMO_SESSION_SECRET` | Signs demo sessions; minimum-length validation in source. | Not inspected; unknown. |
| `HRIS_ALLOWED_ORIGINS` | Optional exact HTTPS origin allowlist additions. | Not inspected; unknown. |
| `HRIS_DATABASE_PATH` | Local SQLite path override; must remain outside served project directory. | Not inspected; unknown. |
| `HRIS_PORT` | Local development server port. | Not inspected; unknown. |
| `HRIS_DEMO_PASSWORD` | Local SQLite demo account password override during first local setup. | Not inspected; unknown. |
| `HRIS_TEST_DATABASE_URL` | Optional isolated Neon integration-test URL. | Not inspected; unknown. |
| `VERCEL`, `VERCEL_ENV`, `VERCEL_URL`, `VERCEL_PROJECT_PRODUCTION_URL` | Vercel runtime/environment/domain context used by code. | Platform-provided values; project runtime values not inspected. |

No `.env` file or secret value was read. The clone’s tracked inventory has no `.env.example`; [.gitignore](../../../.gitignore) excludes environment and local database artifacts.

## Vercel settings that remain unknown

The audit did not use Vercel account access and cannot verify:

- Whether Preview Deployment Protection requires Vercel authentication.
- Whether public access is enabled for Preview or Production.
- Which Git branch Vercel treats as Production or whether the target branch is connected.
- Whether `DATABASE_URL`, demo variables, and allowed origins are configured in Preview vs Production scopes.
- Whether Preview and Production point at separate databases.
- Actual deployment build/runtime logs, current deployed commit, domain aliases, and environment-variable configuration.

These settings must be audited in Vercel Dashboard separately. No deployment, Vercel setting, Production environment variable, or database was changed.

## Migration constraints

Keep the root `api/index.py` convention and static routes until a replacement is deployed and verified. Any new Python packages must be declared in `requirements.txt` and confirmed to bundle. Avoid startup-time database migrations, durable in-process state, and filesystem persistence assumptions. Validate a Preview deployment only after explicit deployment authorization; this audit did not deploy.
