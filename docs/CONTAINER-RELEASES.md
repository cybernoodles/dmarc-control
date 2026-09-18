# Container releases

DMARC Control publishes three independently deployable runtime images from a
reviewed release candidate:

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

The release is intentionally a two-stage process. It ensures that the Git tag
and the release Compose file refer to the exact, immutable image digests.

1. From the reviewed candidate commit, run **Publish container images** through
   the GitHub Actions UI with the intended version, for example `v2.2.2`.
   The workflow runs the frontend, backend, and supervisor tests and publishes
   all three `linux/amd64` and `linux/arm64` images.
2. Resolve the three resulting digests and pin them, together with the version,
   in `docker-compose.release.yml` and `.env.release.example`. Commit that
   release metadata. No Docker build context may change between the candidate
   build and this metadata commit.
3. Create and push the annotated Git tag only after the digest-pinned files are
   committed:

```bash
git tag -a v2.2.2 -m "DMARC Control 2.2.2"
git push origin v2.2.2
```

The tag push runs the test job again, but does not rebuild images. This prevents
an image manifest from changing after its digest has been pinned. Each published
image receives the version tag (`2.2.2`), the minor tag (`2.2`), and an
immutable commit tag. The build also attaches a provenance record and SBOM.

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

## Deploy with Docker Compose

`docker-compose.release.yml` is the ready-to-paste, digest-pinned production
reference. It contains no `build:` entries and creates `dmarc-net`
automatically. Save it as `docker-compose.yml` next to `.env` in one chosen
deployment directory. Set `DMARC_DEPLOYMENT_ROOT` in `.env` to that directory's
absolute path.

The deployment directory contains `.env`, `docker-compose.yml`, `data/`,
`backups/`, `config/` and `dmarc-reports/`. It is the sole source for every
bind mount and for the encrypted configuration copy created by the backup
service.

Before the first deployment, create the bind-mount paths. Docker creates a
missing bind-mount source as `root:root`; that prevents the non-root services
from starting. Set the following shell variable to the exact same absolute
path used for `DMARC_DEPLOYMENT_ROOT` in `.env`:

```bash
export DMARC_DEPLOYMENT_ROOT=__REPLACE_WITH_YOUR_ABSOLUTE_DMARCREAD_DIRECTORY__

sudo install -d -o 1000 -g 1000 -m 0750 "$DMARC_DEPLOYMENT_ROOT/data/opensearch"
sudo install -d -o 10001 -g 10001 -m 0770 "$DMARC_DEPLOYMENT_ROOT/data/dashboard"
sudo install -d -o 10001 -g 10001 -m 0770 "$DMARC_DEPLOYMENT_ROOT/data/parser-control"
sudo install -d -o 10001 -g 10001 -m 2770 "$DMARC_DEPLOYMENT_ROOT/backups"
sudo install -d -o 10001 -g 10001 -m 2770 "$DMARC_DEPLOYMENT_ROOT/backups/opensearch"
sudo install -d -o 10001 -g 10001 -m 2770 "$DMARC_DEPLOYMENT_ROOT/backups/opensearch/repository"
sudo install -d -o 10001 -g 10001 -m 2770 "$DMARC_DEPLOYMENT_ROOT/backups/manifests"
sudo install -d -o 10001 -g 10001 -m 2770 "$DMARC_DEPLOYMENT_ROOT/backups/control"
sudo install -d -o root -g 10001 -m 0750 "$DMARC_DEPLOYMENT_ROOT/config"
sudo install -d -o root -g 10001 -m 0750 "$DMARC_DEPLOYMENT_ROOT/dmarc-reports"

sudo chown -R 1000:1000 "$DMARC_DEPLOYMENT_ROOT/data/opensearch"
sudo chown -R 10001:10001 "$DMARC_DEPLOYMENT_ROOT/data/dashboard" "$DMARC_DEPLOYMENT_ROOT/data/parser-control" "$DMARC_DEPLOYMENT_ROOT/backups"
sudo chmod -R u+rwX,g+rwX "$DMARC_DEPLOYMENT_ROOT/backups"

sudo chown root:10001 "$DMARC_DEPLOYMENT_ROOT/.env" "$DMARC_DEPLOYMENT_ROOT/docker-compose.yml"
sudo chmod 0640 "$DMARC_DEPLOYMENT_ROOT/.env" "$DMARC_DEPLOYMENT_ROOT/docker-compose.yml"
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
it in `DMARC_DEPLOYMENT_ROOT/config/` before deployment; it must be readable by
group `10001`.

The published GHCR packages are public; no registry authentication is required
to pull a release image.

Use the supplied release Compose file for a production deployment. The
repository's source Compose file intentionally retains its local `build:`
definitions for development.
