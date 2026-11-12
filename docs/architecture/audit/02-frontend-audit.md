# 02 — Frontend audit

## Runtime shape

The frontend is static HTML with inline CSS and JavaScript. No frontend framework, bundler, standalone CSS source, or standalone application JavaScript entry was found. [index.html](../../../index.html) is the main shell and the largest frontend responsibility. Tailwind CSS, Font Awesome, and Plus Jakarta Sans are loaded from external CDNs as documented in [README.md](../../../README.md).

## Pages and relationships

| File | Responsibility and dependencies | Target area |
|---|---|---|
| [platform.html](../../../platform.html) | Landing/platform selector; links into existing application experiences. | Shared frontend shell |
| [login.html](../../../login.html) | HRIS login and demo entry; calls the server auth/session APIs and returns to a same-site route. | Shared authentication |
| [index.html](../../../index.html) | Employee Hub shell, localized route views, navigation, server-session gating, HR dashboard/directory client, and Helpdesk prototype. Uses same-origin API calls plus `localStorage` for prototype data. | Split into shared shell and Employee Portal, HRIS Admin, Helpdesk feature modules |
| [admin-login.html](../../../admin-login.html) | Separate Helpdesk prototype login with client-side demo credentials/role. | Replace with shared authentication UI |
| [admin.html](../../../admin.html) | Helpdesk ticket-management prototype; reads/writes browser-local ticket data and checks a client-side session role. | Helpdesk admin view behind backend authorization |

The root `/` behavior is environment-sensitive: `vercel.json` sends it through the API public-entry route; demo mode can redirect to the dashboard, while the normal flow directs to the platform page and existing login flow. `/employee-hub` and `/hris` serve `index.html`; hash fragments represent internal routes.

## Verified feature implementation

### Employee-facing shell

`index.html` has a home/dashboard view, employee profile/navigation entries, announcements, company information/quick links, and Helpdesk entry points. The existence of a menu label is not proof of a functioning HR workflow. The employee portal has no verified employee-specific profile API, attendance persistence, leave workflow, payroll data, or notification service.

### HRIS Admin

The dashboard summary and Employee Directory are the most complete server-backed functions:

- The dashboard calls `GET /api/dashboard/summary`; authorization and aggregates are enforced by the Python handler.
- The directory calls employee list/detail and mutation APIs. Frontend search, filtering, sorting, pagination, forms, and error states depend on the backend contracts.
- Other HRIS route labels intentionally render localized unavailable/placeholder views per [README.md](../../../README.md); they are not implemented modules.

### Helpdesk

Ticket submission, status checking, ticket lists, asset lists, and knowledge content are a browser-side prototype in `index.html` and `admin.html`. Data uses browser `localStorage`, so it is not shared across browsers or devices and is not protected by server authorization. The separate admin login’s session/role is in browser `sessionStorage`. Ticket management controls update local ticket objects; they do not call a Helpdesk API.

## Navigation, localization, and UI

- The main sidebar groups Home, Employee Profile, Employees, Recruitment, Time, Finance, Payroll, Productivity, Company, Applications, Integrations, Settings, and Helpdesk-oriented links.
- Hash-based routes support bookmarked page fragments. Menu labels and selected view content are localized in English and Indonesian.
- Responsive layout, fonts, colors, branding, and sidebar are integrated into `index.html`; preserve those as a visual baseline during extraction.
- Legacy Helpdesk pages have their own layout and navigation rather than sharing a reusable component library.
- Reusable frontend components are not currently organized as source modules. Reuse is primarily through inline templates, helper functions, and shared shell markup.

## Authentication and browser state

- The main shell checks `/api/auth/session` and relies on server-provided session state. Protected API authorization remains a server responsibility.
- The HRIS session cookie is HTTP-only; UI code cannot use that cookie as an authorization source and should continue to rely on backend responses.
- Helpdesk prototype state and data are browser-local. Local storage must be treated as untrusted input and must not be used as evidence of identity or authorization.
- Login destination handling is intended for same-site Employee Hub routes; preserve its safe redirect constraints.
- Demo-mode UI is distinct from HRIS credentials and uses the demo API/session path when enabled.

## Frontend dependency map

| User-visible feature | Current files | Current data/API dependency | Target module |
|---|---|---|---|
| Platform selection | [platform.html](../../../platform.html) | Static routing | Shared shell |
| HRIS login and session UI | [login.html](../../../login.html), [index.html](../../../index.html) | `/api/auth/session`, `/api/auth/login`, `/api/auth/logout`; demo login when enabled | Shared authentication |
| Dashboard aggregates | [index.html](../../../index.html) | `GET /api/dashboard/summary` | HRIS Admin dashboard; separate Employee Portal dashboard contract if required |
| Employee Directory | [index.html](../../../index.html) | `/api/employees` and `/api/employees/{employeeId}` | HRIS Admin / employee module |
| Employee profile/self-service | [index.html](../../../index.html) | No verified self-service API/data model | Employee Portal |
| Attendance, leave, payroll, recruitment | [index.html](../../../index.html) | No verified persistence/API; placeholders | HRIS Admin and Employee Portal submodules as approved |
| Ticket submission/status/list | [index.html](../../../index.html) | Browser `localStorage`; no backend API | Helpdesk |
| Ticket administration | [admin.html](../../../admin.html), [admin-login.html](../../../admin-login.html) | Browser `localStorage` and `sessionStorage` | Helpdesk, shared auth and server API |
| Assets and knowledge base | [index.html](../../../index.html) | Browser-local/mock content | Helpdesk |

## Frontend risks and migration constraints

1. Extracting code from `index.html` can break fragment routing, event wiring, language switching, menu state, or responsive styling. Characterize these behaviors before moving code.
2. Prototype data saved in local storage can contain stale or user-controlled values. Do not silently import it as trusted server data.
3. Keep all displayed demo records synthetic and segregated from real HR records.
4. Remove hardcoded/demo client-side credentials from any production trust boundary; server authorization must gate Helpdesk administration.
5. CDN assets create availability, supply-chain, and privacy dependencies. Pinning/self-hosting may be considered separately; do not make a framework migration a prerequisite.
6. Preserve current branding and page behavior by extracting markup/styles without redesign. Add browser tests for root entry, refresh, module navigation, and responsive menu behavior before a large split.

See [06-feature-mapping.md](06-feature-mapping.md) for implementation status by feature.
