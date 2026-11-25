# API del panel

<!-- Generado por apps/backend/src/tools/docs/openapi_md.py desde apps/panel/openapi.json.
     No editar: ejecuta `make api`. -->

!!! warning "Generado, no editar"
    Esta página sale de `apps/panel/openapi.json` con `make api`. Si hay que cambiarla,
    se cambia el código del router y se regenera.

Referencia de la API interna del panel. Léela para saber qué endpoints hay y qué reciben y
devuelven. Todas las rutas cuelgan de `/api/panel` y solo son accesibles por túnel SSH
(ADR-008). Salvo `GET /auth/csrf` y `POST /auth/login`, exigen la cookie de sesión
`autobot_panel_session`; las peticiones que modifican datos exigen además el token CSRF.
Cómo se organiza el panel está en [panel](../arquitectura/panel.md).

## activity

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/activity` | Activity | ActivityPage |
| GET | `/api/panel/activity/{kind}/{id}` | Activity Detail View | ActivityDetail |

Parámetros y cuerpos:

- `GET /api/panel/activity`
    - Parámetro `cursor` (query): string
    - Parámetro `kinds` (query): string
    - Parámetro `limit` (query): integer
    - Parámetro `status` (query): string
    - Parámetro `tenant` (query): string
- `GET /api/panel/activity/{kind}/{id}`
    - Parámetro `id` (path, obligatorio): string
    - Parámetro `kind` (path, obligatorio): string

## audit

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/audit` | Audit | AuditPage |
| GET | `/api/panel/audit/actions` | Audit Actions | string[] |

Parámetros y cuerpos:

- `GET /api/panel/audit`
    - Parámetro `action` (query): string
    - Parámetro `cursor` (query): string
    - Parámetro `limit` (query): integer
    - Parámetro `tenant` (query): string

## auth

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/auth/csrf` | Csrf | sin cuerpo |
| POST | `/api/panel/auth/login` | Login | sin cuerpo |
| POST | `/api/panel/auth/logout` | Logout | sin cuerpo |
| GET | `/api/panel/auth/me` | Me | sin cuerpo |
| POST | `/api/panel/auth/step-up` | Step Up | sin cuerpo |

Parámetros y cuerpos:

- `POST /api/panel/auth/login`
    - Cuerpo: LoginIn
        - `otp`: string
        - `password`: string
        - `username`: string
- `POST /api/panel/auth/step-up`
    - Cuerpo: StepUpIn
        - `otp`: string

## calendar

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/calendar/service-account` | Service Account | ServiceAccountOut |

## contacts

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/contacts/{id}` | Contact Detail | ContactDetail |
| GET | `/api/panel/contacts/{id}/export` | Contact Export | ContactExportOut |
| POST | `/api/panel/contacts/{id}/forget` | Contact Forget | ContactForgetOut |
| GET | `/api/panel/tenants/{slug}/contacts` | Contacts | ContactPage |

Parámetros y cuerpos:

- `GET /api/panel/contacts/{id}`
    - Parámetro `id` (path, obligatorio): string (uuid)
- `GET /api/panel/contacts/{id}/export`
    - Parámetro `id` (path, obligatorio): string (uuid)
- `POST /api/panel/contacts/{id}/forget`
    - Parámetro `id` (path, obligatorio): string (uuid)
- `GET /api/panel/tenants/{slug}/contacts`
    - Parámetro `slug` (path, obligatorio): string
    - Parámetro `cursor` (query): string
    - Parámetro `limit` (query): integer
    - Parámetro `search` (query): string

## data

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| POST | `/api/panel/data/query` | Run Query | QueryOut |
| GET | `/api/panel/data/tables` | Tables | TableSummaryOut[] |
| GET | `/api/panel/data/tables/{name}` | Table | TableDetailOut |

Parámetros y cuerpos:

- `POST /api/panel/data/query`
    - Cuerpo: QueryIn
        - `sql`: string
        - `tenant` (opcional): string
- `GET /api/panel/data/tables/{name}`
    - Parámetro `name` (path, obligatorio): string

## demo-invites

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/demo/invites` | List Invites | DemoInvitePage |
| POST | `/api/panel/demo/invites` | Create | DemoInviteOut |
| GET | `/api/panel/demo/invites/{id}/qr` | Qr | DemoInviteQr |
| POST | `/api/panel/demo/invites/{id}/revoke` | Revoke | DemoInviteOut |

Parámetros y cuerpos:

- `GET /api/panel/demo/invites`
    - Parámetro `cursor` (query): string
    - Parámetro `limit` (query): integer
- `POST /api/panel/demo/invites`
    - Cuerpo: DemoInviteCreate
        - `expires_in_days`: integer | null
        - `max_uses` (opcional): integer
        - `note` (opcional): string
- `GET /api/panel/demo/invites/{id}/qr`
    - Parámetro `id` (path, obligatorio): string (uuid)
- `POST /api/panel/demo/invites/{id}/revoke`
    - Parámetro `id` (path, obligatorio): string (uuid)

## incidents

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/alerts` | Alerts | AlertsPage |
| POST | `/api/panel/alerts/{id}/resolve` | Resolve | MessageOut |
| GET | `/api/panel/incidents` | Incidents | IncidentsOut |
| GET | `/api/panel/jobs` | Jobs | JobsPage |
| POST | `/api/panel/jobs/{id}/retry` | Retry | MessageOut |
| POST | `/api/panel/outbound/resend-bulk` | Resend Bulk | BulkResendOut |
| POST | `/api/panel/outbound/resend-bulk/preview` | Resend Bulk Preview | BulkPreviewOut |
| POST | `/api/panel/outbound/{id}/mark-sent` | Mark Sent | MessageOut |
| POST | `/api/panel/outbound/{id}/resend` | Resend | MessageOut |

Parámetros y cuerpos:

- `GET /api/panel/alerts`
    - Parámetro `cursor` (query): string
    - Parámetro `limit` (query): integer
    - Parámetro `state` (query): string
- `POST /api/panel/alerts/{id}/resolve`
    - Parámetro `id` (path, obligatorio): string (uuid)
- `GET /api/panel/incidents`
    - Parámetro `limit` (query): integer
- `GET /api/panel/jobs`
    - Parámetro `cursor` (query): string
    - Parámetro `limit` (query): integer
    - Parámetro `queue` (query): string
    - Parámetro `status` (query): string
- `POST /api/panel/jobs/{id}/retry`
    - Parámetro `id` (path, obligatorio): integer
- `POST /api/panel/outbound/resend-bulk`
    - Cuerpo: BulkResendIn
        - `confirm_duplicate_risk` (opcional): any
        - `ids` (opcional): string (uuid)[] | null
        - `since` (opcional): string (date-time) | null
        - `statuses` (opcional): string[]
        - `tenant_id` (opcional): string (uuid) | null
        - `until` (opcional): string (date-time) | null
- `POST /api/panel/outbound/resend-bulk/preview`
    - Cuerpo: BulkFilter
        - `since` (opcional): string (date-time) | null
        - `statuses` (opcional): string[]
        - `tenant_id` (opcional): string (uuid) | null
        - `until` (opcional): string (date-time) | null
- `POST /api/panel/outbound/{id}/mark-sent`
    - Parámetro `id` (path, obligatorio): string (uuid)
- `POST /api/panel/outbound/{id}/resend`
    - Parámetro `id` (path, obligatorio): string (uuid)
    - Cuerpo (opcional): Confirmation | null

## logs

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/logs` | Logs | LogsOut |

Parámetros y cuerpos:

- `GET /api/panel/logs`
    - Parámetro `end` (query): string (date-time) | null
    - Parámetro `level` (query): string
    - Parámetro `limit` (query): integer
    - Parámetro `q` (query): string
    - Parámetro `service` (query): string
    - Parámetro `start` (query): string (date-time) | null
    - Parámetro `tenant` (query): string

## overview

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/overview` | Overview | Overview |

## packs

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/packs` | Packs | PackOut[] |
| GET | `/api/panel/packs/{pack}/datasets/{dataset}/library` | Dataset Library Entries | LibraryEntryOut[] |
| GET | `/api/panel/packs/{pack}/schema` | Pack Schema | PackSchemaOut |
| GET | `/api/panel/packs/{pack}/template` | Pack Template | PackTemplateOut |

Parámetros y cuerpos:

- `GET /api/panel/packs/{pack}/datasets/{dataset}/library`
    - Parámetro `dataset` (path, obligatorio): string
    - Parámetro `pack` (path, obligatorio): string
- `GET /api/panel/packs/{pack}/schema`
    - Parámetro `pack` (path, obligatorio): string
- `GET /api/panel/packs/{pack}/template`
    - Parámetro `pack` (path, obligatorio): string

## system

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/system` | System | SystemOut |
| GET | `/api/panel/system/config` | System Config | ConfigStateOut |

## tenants

| Método | Ruta | Resumen | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/panel/tenant-slug-availability` | Tenant Slug Availability | SlugAvailability |
| GET | `/api/panel/tenants` | List Tenants | TenantRow[] |
| POST | `/api/panel/tenants` | Create Tenant | VersionOut |
| GET | `/api/panel/tenants/{slug}` | Tenant Detail | TenantDetail |
| GET | `/api/panel/tenants/{slug}/activation-checklist` | Tenant Checklist | ChecklistItemOut[] |
| GET | `/api/panel/tenants/{slug}/datasets/{dataset}` | Tenant Dataset Status | DatasetStatusOut |
| POST | `/api/panel/tenants/{slug}/datasets/{dataset}/apply` | Apply Dataset | VersionOut |
| POST | `/api/panel/tenants/{slug}/delete` | Delete Tenant | DeleteTenantOut |
| PUT | `/api/panel/tenants/{slug}/document` | Publish Document | VersionOut |
| POST | `/api/panel/tenants/{slug}/export` | Tenant Export | ExportOut |
| POST | `/api/panel/tenants/{slug}/health-check` | Tenant Health Check | HealthIssueOut[] |
| GET | `/api/panel/tenants/{slug}/notifications` | Tenant Notifications | NotificationPage |
| POST | `/api/panel/tenants/{slug}/owner-invite` | Tenant Owner Invite | OwnerInviteOut |
| POST | `/api/panel/tenants/{slug}/owner-unlink` | Tenant Owner Unlink | OwnerUnlinkOut |
| POST | `/api/panel/tenants/{slug}/rollback` | Rollback Document | VersionOut |
| GET | `/api/panel/tenants/{slug}/secrets` | Tenant Secrets | SecretsStatus |
| PUT | `/api/panel/tenants/{slug}/secrets` | Set Secrets | SecretsUpdateOut |
| GET | `/api/panel/tenants/{slug}/setup` | Tenant Setup | SetupStepOut[] |
| POST | `/api/panel/tenants/{slug}/setup/action/{step}` | Tenant Setup Action | SetupStepOut |
| POST | `/api/panel/tenants/{slug}/setup/check/{step}` | Tenant Setup Check | SetupStepOut |
| POST | `/api/panel/tenants/{slug}/setup/testers` | Tenant Setup Add Tester | SetupStepOut |
| POST | `/api/panel/tenants/{slug}/status` | Change Status | VersionOut |
| GET | `/api/panel/tenants/{slug}/summary` | Tenant Summary | SummaryOut |
| GET | `/api/panel/tenants/{slug}/telegram-webhook` | Telegram Webhook Status | WebhookStatusOut |
| POST | `/api/panel/tenants/{slug}/telegram-webhook` | Telegram Set Webhook | WebhookRegisterOut |
| GET | `/api/panel/tenants/{slug}/versions` | Tenant Versions | VersionSummary[] |
| GET | `/api/panel/tenants/{slug}/versions/{version}` | Tenant Version | VersionDetail |

Parámetros y cuerpos:

- `GET /api/panel/tenant-slug-availability`
    - Parámetro `slug` (query, obligatorio): string
- `POST /api/panel/tenants`
    - Cuerpo: CreateTenantIn
        - `channel_type` (opcional): "whatsapp" | "telegram" | null
        - `comment` (opcional): string
        - `config`: object
        - `dataset_choices` (opcional): object | null
        - `demo_description` (opcional): string | null
        - `name`: string
        - `pack`: string
        - `slug`: string
        - `timezone`: string
- `GET /api/panel/tenants/{slug}`
    - Parámetro `slug` (path, obligatorio): string
- `GET /api/panel/tenants/{slug}/activation-checklist`
    - Parámetro `slug` (path, obligatorio): string
- `GET /api/panel/tenants/{slug}/datasets/{dataset}`
    - Parámetro `dataset` (path, obligatorio): string
    - Parámetro `slug` (path, obligatorio): string
- `POST /api/panel/tenants/{slug}/datasets/{dataset}/apply`
    - Parámetro `dataset` (path, obligatorio): string
    - Parámetro `slug` (path, obligatorio): string
    - Cuerpo: ApplyDatasetIn
        - `comment` (opcional): string
        - `name`: string
        - `version` (opcional): integer | null
- `POST /api/panel/tenants/{slug}/delete`
    - Parámetro `slug` (path, obligatorio): string
    - Cuerpo: DeleteTenantIn
        - `confirm_slug`: string
- `PUT /api/panel/tenants/{slug}/document`
    - Parámetro `slug` (path, obligatorio): string
    - Cuerpo: DocumentIn
        - `base_version`: integer
        - `comment` (opcional): string
        - `document`: object
- `POST /api/panel/tenants/{slug}/export`
    - Parámetro `slug` (path, obligatorio): string
- `POST /api/panel/tenants/{slug}/health-check`
    - Parámetro `slug` (path, obligatorio): string
- `GET /api/panel/tenants/{slug}/notifications`
    - Parámetro `slug` (path, obligatorio): string
    - Parámetro `cursor` (query): string
    - Parámetro `limit` (query): integer
- `POST /api/panel/tenants/{slug}/owner-invite`
    - Parámetro `slug` (path, obligatorio): string
- `POST /api/panel/tenants/{slug}/owner-unlink`
    - Parámetro `slug` (path, obligatorio): string
- `POST /api/panel/tenants/{slug}/rollback`
    - Parámetro `slug` (path, obligatorio): string
    - Cuerpo: RollbackIn
        - `comment`: string
        - `version`: integer
- `GET /api/panel/tenants/{slug}/secrets`
    - Parámetro `slug` (path, obligatorio): string
- `PUT /api/panel/tenants/{slug}/secrets`
    - Parámetro `slug` (path, obligatorio): string
    - Cuerpo: SecretsIn
        - `secrets`: object
- `GET /api/panel/tenants/{slug}/setup`
    - Parámetro `slug` (path, obligatorio): string
- `POST /api/panel/tenants/{slug}/setup/action/{step}`
    - Parámetro `slug` (path, obligatorio): string
    - Parámetro `step` (path, obligatorio): string
    - Cuerpo: SetupActionIn
        - `pin` (opcional): string | null
- `POST /api/panel/tenants/{slug}/setup/check/{step}`
    - Parámetro `slug` (path, obligatorio): string
    - Parámetro `step` (path, obligatorio): string
- `POST /api/panel/tenants/{slug}/setup/testers`
    - Parámetro `slug` (path, obligatorio): string
    - Cuerpo: AddTesterIn
        - `id`: string
- `POST /api/panel/tenants/{slug}/status`
    - Parámetro `slug` (path, obligatorio): string
    - Cuerpo: StatusIn
        - `action`: string
        - `confirm_slug` (opcional): string | null
- `GET /api/panel/tenants/{slug}/summary`
    - Parámetro `slug` (path, obligatorio): string
- `GET /api/panel/tenants/{slug}/telegram-webhook`
    - Parámetro `slug` (path, obligatorio): string
- `POST /api/panel/tenants/{slug}/telegram-webhook`
    - Parámetro `slug` (path, obligatorio): string
- `GET /api/panel/tenants/{slug}/versions`
    - Parámetro `slug` (path, obligatorio): string
    - Parámetro `before` (query): integer | null
    - Parámetro `limit` (query): integer
- `GET /api/panel/tenants/{slug}/versions/{version}`
    - Parámetro `slug` (path, obligatorio): string
    - Parámetro `version` (path, obligatorio): integer
