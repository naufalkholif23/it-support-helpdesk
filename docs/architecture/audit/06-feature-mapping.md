# 06 — Feature mapping

**Classification key:** Implemented means there is working code and a verified backend/data path in source. Partially implemented means a meaningful but incomplete workflow exists. Prototype means browser-local or demo-only behavior without production-grade backend/security. Placeholder means navigation/view exists but the business workflow is not implemented. Not found means no source evidence was found. Unknown means repository evidence is insufficient.

## Employee Portal

| Feature | Status | Evidence and notes |
|---|---|---|
| Employee dashboard | Partially implemented | `index.html` has a welcome/home experience and links; HR aggregates are admin-role-only. No personalized employee dashboard API/data scoping. |
| Employee profile | Placeholder | Navigation/view shell exists, but no verified employee-to-user mapping or self-service profile API. |
| Attendance | Placeholder | Menu/localized labels exist; no attendance model, endpoint, or verified persisted workflow. |
| Leave/permission requests | Placeholder | No verified leave model, approval API, or persisted workflow. A generic Helpdesk request is not a leave workflow. |
| Employee self-service | Placeholder | No verified employee-scoped API or identity ownership policy. |
| Notifications | Not found / Unknown | No server notification service or notification persistence found; some UI elements/local content do not prove a notification workflow. |
| Announcements | Prototype | Frontend/local content and local storage key exist; no verified authorized server-backed publishing/reading workflow. |
| Company information and quick links | Prototype | Static/local content in frontend; no server workflow required for basic informational links. |
| Payslips | Not found | No payroll/payslip schema, protected document store, API, or workflow found. |
| Overtime | Not found | No verified overtime model/API/workflow. |

## HRIS Admin

| Feature | Status | Evidence and notes |
|---|---|---|
| HR dashboard summary | Implemented | Server aggregate endpoint in `hris_server.py`; restricted to HR/system admins. Metrics are constrained by available employee schema. |
| Employee directory | Implemented | Search/filter/sort/page, detail, validated create/update/delete, role checks, conflict behavior, and audit logging. |
| Attendance administration | Placeholder | No data model or endpoint found. |
| Leave management/approval | Placeholder | No data model or endpoint found. |
| Recruitment | Placeholder | Menu/view labels only; no verified applicant workflow or persistence. |
| Payroll/finance | Placeholder | No payroll transactions, salary model, payslips, or finance backend found. Do not infer transactions from navigation. |
| Company asset inventory | Prototype / Placeholder | UI/local content exists, but no shared server persistence or server-side access control. |
| Reports | Placeholder | No verified reporting service beyond the HR dashboard aggregates. |
| KPI/time tracker | Placeholder | No verified model, API, or workflow. |
| Settings | Placeholder | Navigation exists; no verified settings-management service. |
| Audit logs | Partially implemented | Employee CRUD actions are recorded in `audit_logs`; no general audit-log query UI, retention policy, or comprehensive event coverage verified. |

## Helpdesk

| Feature | Status | Evidence and notes |
|---|---|---|
| Ticket submission | Prototype | Browser-side form and `localStorage`; no backend endpoint or cross-device persistence. |
| Ticket list/status lookup | Prototype | Reads browser-local data; not a centralized service. |
| Ticket administration/status/PIC/resolution updates | Prototype | `admin.html` updates local ticket storage; admin trust is client-side only. |
| IT support workflow | Prototype | UI interactions exist, but no server-side queue, authorization, assignment, or audit trail. |
| Asset listing | Prototype | Browser-side/local content; no server-backed asset inventory. |
| Knowledge base/SOP | Prototype | Static/local content; no verified content administration or publication backend. |
| Helpdesk authentication/permissions | Placeholder for production | Separate demo credential/session check in browser, not suitable for real authorization. |

## Overall conclusion

The verified production-like core is authentication/session handling plus HR-admin employee directory and aggregate dashboard. The broader employee life-cycle and Helpdesk workflows are currently navigation shells, static content, or browser-only prototypes. Preserve these surfaces during migration, but do not label them as production-ready capabilities or connect them to real data until backend and permission requirements are approved.

## Shared platform requirements

The agreed modular monolith should share one authentication/authorization layer and one primary database. That requires explicit future design for:

- A verified mapping between HRIS users and employee records for self-service.
- Helpdesk roles/permissions, which are absent from the current `users.role` constraint.
- Backend persistence and API authorization for tickets/assets if Helpdesk is to be a real module.
- A policy for anonymous ticket submission versus signed-in employee tickets.
- Data retention and migration policy for existing browser-local prototype data.

No feature implementation or schema migration was performed in this audit.
