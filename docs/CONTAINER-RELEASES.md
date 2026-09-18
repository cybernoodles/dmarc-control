# Container releases

DMARC Control publishes three independently deployable runtime images when a
version tag is pushed:

| Image | Content |
| --- | --- |
| `ghcr.io/cybernoodles/dmarc-control-dashboard` | The web UI and its FastAPI backend |
| `ghcr.io/cybernoodles/dmarc-control-parser` | The DMARC Control supervisor on the pinned upstream parsedmarc image |
| `ghcr.io/cybernoodles/dmarc-control-backup` | The isolated scheduled backup worker |

The parser and backup images are intentionally separate from the dashboard
image. This keeps the mailbox consumer and scheduled backup worker, their
least-privilege mounts, and their restart lifecycles independent from the web
service.

## Create a release

Run the full test suite before creating a tag. A pushed annotated version tag
such as `v2.2.1` starts `.github/workflows/publish-images.yml`:

```bash
git tag -a v2.2.1 -m "DMARC Control 2.2.1"
git push origin v2.2.1
```

The workflow runs the frontend and backend tests, then builds and publishes
all three images for `linux/amd64` and `linux/arm64`. Each image receives the
version tag (`2.2.1`), the minor tag (`2.2`), and an immutable commit tag.
It also attaches a build provenance record and SBOM.

The first published packages must be made public in their GitHub Package
settings if installations should pull them without a registry login. Keep the
package linked to this repository; the OCI source label supplies that link.

## Deploy a release

Resolve each published version to a digest, then pin that exact reference in
the production Compose configuration. Do not deploy `latest`, a mutable minor
tag, or an unpinned version tag.

```yaml
dashboard:
  image: ghcr.io/cybernoodles/dmarc-control-dashboard:1.4.0@sha256:REPLACE_WITH_DASHBOARD_DIGEST

parsedmarc:
  image: ghcr.io/cybernoodles/dmarc-control-parser:1.4.0@sha256:REPLACE_WITH_PARSER_DIGEST

backup:
  image: ghcr.io/cybernoodles/dmarc-control-backup:1.4.0@sha256:REPLACE_WITH_BACKUP_DIGEST
```

The published parser image includes the project's supervisor; it must not be
replaced with the bare `ghcr.io/domainaware/parsedmarc` image.

## Deploy with Dockge or Docker Compose

`docker-compose.release.yml` is the ready-to-paste, digest-pinned production
reference. It contains no `build:` entries and creates `dmarc-net`
automatically. Copy its contents into Dockge as `compose.yaml`, copy
`.env.release.example` into the Dockge environment editor or `.env`, and set
the four absolute-path values at the top of that file.

For a standard Docker Compose deployment, keep the Compose file and `.env` in
any directory, set the same values to the actual absolute locations, and run
Compose with `-f docker-compose.release.yml`.

Before the first deployment, create the bind-mount paths. Docker creates a
missing bind-mount source as `root:root`; that prevents the non-root services
from starting. The following Dockge example separates stack definitions from
persistent data:

```bash
sudo install -d -o 1000 -g 1000 -m 0750 /opt/dmarc-control/data/opensearch
sudo install -d -o 10001 -g 10001 -m 0770 /opt/dmarc-control/data/dashboard
sudo install -d -o 10001 -g 10001 -m 0770 /opt/dmarc-control/data/parser-control
sudo install -d -o 10001 -g 10001 -m 2770 /opt/dmarc-control/backups
sudo install -d -o 10001 -g 10001 -m 2770 /opt/dmarc-control/backups/opensearch
sudo install -d -o 10001 -g 10001 -m 2770 /opt/dmarc-control/backups/opensearch/repository
sudo install -d -o 10001 -g 10001 -m 2770 /opt/dmarc-control/backups/manifests
sudo install -d -o 10001 -g 10001 -m 2770 /opt/dmarc-control/backups/control
sudo install -d -o root -g 10001 -m 0750 /opt/dmarc-control/config
sudo install -d -o root -g 10001 -m 0750 /opt/dmarc-control/dmarc-reports

sudo chown -R 1000:1000 /opt/dmarc-control/data/opensearch
sudo chown -R 10001:10001 /opt/dmarc-control/data/dashboard /opt/dmarc-control/data/parser-control
sudo chown -R 10001:10001 /opt/dmarc-control/backups
sudo chmod -R u+rwX,g+rwX /opt/dmarc-control/backups

sudo chown root:10001 /opt/stacks/dmarc-control/.env /opt/stacks/dmarc-control/compose.yaml
sudo chmod 0640 /opt/stacks/dmarc-control/.env /opt/stacks/dmarc-control/compose.yaml
sudo sysctl -w vm.max_map_count=262144
```

`install -d` creates the directories with their owner, group and mode in a
single step; `mkdir -p` only creates them. The backup tree uses `2770` so new
snapshot files inherit group `10001`, which OpenSearch receives as a
supplementary group. The recursive `chown` and `chmod` lines are also the safe
repair procedure for a tree that already exists with incorrect ownership.

The `config/` directory may stay empty for a new GUI-managed mailbox setup.
The parser becomes healthy after the administrator has tested and activated a
mailbox connection in the dashboard. If using a legacy `parsedmarc.ini`, place
it in `DMARC_DATA_ROOT/config/` before deployment; it must be readable by
group `10001`.

For private GHCR packages, authenticate the Docker user that performs the
pull. Dockge needs access to that Docker credential configuration too; mount
`/root/.docker:/root/.docker:ro` into the Dockge service and recreate Dockge.

Once all three release digests are available, the production Compose file can
replace its remaining `build:` blocks with these pinned image references.
