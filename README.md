<p align="center">
  <img
    src="./docs/assets/logo-restart/alternatives/dmarc-control-gate-precision.png"
    alt="DMARC Control logo"
    width="240"
  >
</p>

<h1 align="center">DMARC Control</h1>

<p align="center">
  <strong>Understand DMARC reports, control sending sources, and act on risk.</strong>
</p>

<p align="center">
  Self-hosted DMARC monitoring with a web-first setup and operations workflow.
</p>

<p align="center">
  <img alt="Deployment: Docker Compose" src="https://img.shields.io/badge/Deployment-Docker%20Compose-2496ED?logo=docker&amp;logoColor=white">
  <img alt="Web UI: standard" src="https://img.shields.io/badge/Web%20UI-standard-2563EB">
  <img alt="Grafana: optional" src="https://img.shields.io/badge/Grafana-optional-F46800?logo=grafana&amp;logoColor=white">
</p>

<p align="center">
  <a href="#standard-installation-web-ui">Installation</a> ·
  <a href="#post-installation">Post-installation</a> ·
  <a href="#optional-grafana">Grafana</a> ·
  <a href="#operations">Operations</a>
</p>

DMARC Control is a self-hosted platform for collecting, analysing, and acting
on DMARC reports. It combines
[parsedmarc](https://github.com/domainaware/parsedmarc), OpenSearch, and a
dedicated React/FastAPI application in a Docker Compose deployment.

The normal data flow is:

`DMARC mailbox → parsedmarc → OpenSearch → DMARC Control web UI`

The web UI is the standard interface. Grafana is available as an optional
analytics view for existing or specialised deployments.

## Product overview

DMARC Control provides:

- a risk-focused overview of message volume, DMARC pass rates, failures,
  policies, report freshness, and trends;
- a sending-host inventory with IP, PTR, ASN, country, identities, service
  detection, confidence, and manual classification;
- domain monitoring and explainable Microsoft 365 sender assessment based on
  MX, SPF, DKIM, and DMARC history;
- persistent alert triage with open, acknowledged, resolved, and ignored
  states;
- managed report ingestion through Microsoft Graph or IMAP;
- optional alert email delivery through SMTP or Microsoft Graph;
- privacy-conscious defaults: forensic/RUF storage is disabled unless it is
  explicitly enabled.

Microsoft 365 assessment adds context; it is not an allowlist. A confirmed or
automatically expected provider can calm a fully DMARC-passing new-source
event, but DMARC failures remain critical.

## Standard installation: web UI

Grafana is not required for the standard installation.

### Requirements

- A Linux host with Docker Engine and Docker Compose v2
- Permission to create the persistent data directories with the required UIDs
- TCP port `3030` available for the web UI
- `vm.max_map_count=262144` for OpenSearch

Set the OpenSearch kernel requirement:

```bash
sudo sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262144" | sudo tee /etc/sysctl.d/99-opensearch.conf
```

### Prepare the project

```bash
git clone https://github.com/cybernoodles/dmarc-control.git
cd dmarc-control
cp .env.example .env
```

Edit `.env` and replace `OPENSEARCH_ADMIN_PASSWORD` with a strong bootstrap
password. Keep these values empty for the standard installation:

```dotenv
COMPOSE_PROFILES=
GRAFANA_ADMIN_PASSWORD=
```

Do not commit `.env`; it is installation-specific and may contain secrets.

### Prepare persistent storage

```bash
mkdir -p data/opensearch data/dashboard data/parser-control dmarc-reports
sudo chown 1000:1000 data/opensearch
sudo chown 10001:10001 data/dashboard data/parser-control
```

OpenSearch runs as UID `1000`. DMARC Control and its parser-control files use
UID `10001`. Incorrect ownership can prevent service startup or persistent
writes.

### Start the stack

```bash
docker compose up -d --build --remove-orphans
docker compose ps
```

Open `http://HOSTNAME_OR_IP:3030`.

For Dockge, use the repository root as the stack directory because Compose
resolves all relative paths from the Compose file location. See
[Dashboard and operations](docs/CUSTOM-DASHBOARD.md) for deployment notes.

### Complete first-time setup

The first browser visit opens the setup screen. Create:

- a read username and password for normal dashboard access;
- a separate administrator password for protected settings.

Both passwords must contain at least 12 characters. The dashboard is available
after setup, but report ingestion remains idle until a mailbox connection has
been tested and activated. On a clean installation, `docker compose ps` may
show `parsedmarc` as unhealthy until that activation; this is expected.

## Post-installation

### Connect a report mailbox

Open **Settings → Mailbox connection**, authenticate as administrator, and
choose Microsoft 365 or IMAP.

The workflow is deliberately explicit:

1. Save the connection as a draft.
2. Run **Test connection**.
3. Review the result.
4. Activate the successfully tested revision.

The connection test is read-only. It verifies authentication and access to the
configured folders without reading, moving, or deleting report messages.
Activation starts report processing with the selected revision.

For Microsoft 365, use a dedicated report mailbox and create the report and
archive folders before testing the connection. The defaults are
`Inbox/DMARC` and `Inbox/DMARC/Processed`. The current UI supports client-secret
authentication. Assign `Application Mail.ReadWrite` through Exchange Online
Application RBAC scoped to the dedicated mailbox; do not add a tenant-wide
grant for the same permission. See
[Microsoft 365 mailbox integration](docs/M365.md) for the complete setup and
verification procedure.

For IMAP, provide the TLS-enabled server, credentials, report folder, and
archive folder in the same screen.

### Configure email notifications

Notifications are disabled by default. Open **Settings → Notifications** and
configure one of these transports:

- SMTP with STARTTLS, implicit TLS, or an explicitly trusted internal relay;
- Microsoft Graph with `Mail.Send`, ideally restricted to the configured
  sender mailbox.

Set the sender, recipients, language, public dashboard URL, and event types.
Save the settings, send a test message, and only then enable automatic
notifications. A test message does not enable alerting by itself.

### Review monitored domains

Open **Settings → Domains** to add expected domains, retire unused domains, and
review Microsoft 365 evidence. Administrators can confirm or reject the
automatic provider assessment without weakening DMARC-failure handling.

### Verify report processing

After mailbox activation, wait for the first DMARC aggregate report and check
the overview. Parser logs are available with:

```bash
docker compose logs -f parsedmarc
```

## Container releases

Version tags publish the dashboard and parser/supervisor as multi-architecture
images to GitHub Container Registry. The parser image retains the DMARC Control
supervisor; it is not interchangeable with the bare upstream parsedmarc image.
See [Container releases](docs/CONTAINER-RELEASES.md) for the release and
digest-pinning procedure, including the mandatory bind-mount preparation for
Dockge and standalone Docker Compose deployments.

## Optional Grafana

Grafana can be used as the primary analytics view, but it does not replace the
DMARC Control service. Initial setup, mailbox management, domain settings,
alert triage, and notifications remain in the web UI.

Enable the profile in `.env`:

```dotenv
COMPOSE_PROFILES=grafana
GRAFANA_ADMIN_PASSWORD=REPLACE_WITH_A_STRONG_PASSWORD
```

Prepare its persistent directory and update the stack:

```bash
mkdir -p data/grafana
sudo chown 472:472 data/grafana
docker compose up -d --build --remove-orphans
```

Open `http://HOSTNAME_OR_IP:3020` and sign in as `admin` with the password from
`.env`. The repository provisions overview, analysis, and forensic dashboards.
The forensic dashboard remains empty while forensic/RUF storage is disabled.

## Security and data

- OpenSearch has no host-published port and is used over the internal Compose
  network. Do not publish its port directly.
- Port `3030` serves HTTP by default. Do not expose it directly to the public
  internet; use a firewall and an HTTPS reverse proxy for remote access.
- Mailbox and notification secrets are encrypted before they are stored in
  `data/dashboard/dashboard.db`. The matching key is stored in
  `data/dashboard/connection.key`.
- Forensic/RUF reports can contain personal or sensitive message metadata and
  are disabled by default. Enable them only with an approved retention and
  access policy.
- A complete recovery requires consistent backups of the persistent data and
  installation configuration. Do not copy the live OpenSearch directory as a
  backup. Follow [Backup and restore](docs/BACKUP-RESTORE.md) before operating
  the stack in production.

## Operations

### Update

Installations created with older Docker volumes may require a one-time data
migration. Read [Migration to portable data](docs/MIGRATION-TO-PORTABLE-DATA.md)
first. If the installation still uses the old volumes, stop and migrate it
before running the Compose update below.

```bash
git pull --ff-only
docker compose up -d --build --remove-orphans
```

### Basic checks

```bash
docker compose ps
curl -fsS http://localhost:3030/api/health
docker compose logs --tail=100 dashboard parsedmarc opensearch
```

## Further documentation

| Document | Purpose |
|---|---|
| [Microsoft 365 mailbox integration](docs/M365.md) | Dedicated mailbox, Graph permissions, and Exchange Application RBAC |
| [Dashboard and operations](docs/CUSTOM-DASHBOARD.md) | Architecture, APIs, alerting behaviour, and Dockge notes |
| [Backup and restore](docs/BACKUP-RESTORE.md) | Data ownership, consistency requirements, and recovery order |
| [Migration to portable data](docs/MIGRATION-TO-PORTABLE-DATA.md) | Moving older Docker volumes into the current bind-mount layout |

The Compose and Docker build files are the source of truth for component
versions, container settings, published ports, and optional profiles.
