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
such as `v1.4.0` starts `.github/workflows/publish-images.yml`:

```bash
git tag -a v1.4.0 -m "DMARC Control 1.4.0"
git push origin v1.4.0
```

The workflow runs the frontend and backend tests, then builds and publishes
both images for `linux/amd64` and `linux/arm64`. Each image receives the
version tag (`1.4.0`), the minor tag (`1.4`), and an immutable commit tag.
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

Once all three release digests are available, the production Compose file can
replace its remaining `build:` blocks with these pinned image references.
