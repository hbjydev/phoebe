# Updates

Phoebe uses [Renovate](https://docs.renovatebot.com/) to automatically propose
updates for all dependencies. This includes Helm chart versions, container
images, and GitHub Actions.

## How Renovate Works

### 1. Automated Scanning

Renovate scans the repository for:

- **Helm charts** (via HelmRelease manifests)
- **Container images** (via Kubernetes deployments, pods, etc.)
- **Flux OCI repositories** (container-based Helm charts)
- **GitHub Actions** (in `.github/workflows/`)

### 2. Pull Request Creation

When updates are available, Renovate:

1. Creates a new branch with the update
2. Opens a pull request with detailed changelog information
3. Automatically merges if configured (via `:automergeBranch`)

### 3. Flux Reconciliation

After merging:

1. Flux detects the change in the Git repository
2. HelmRelease or manifest changes are applied to the cluster
3. New container images are pulled and deployed

## Configuration

Renovate configuration is in `.renovaterc.json5`:

```json5
{
  extends: [
    "config:recommended",
    "docker:enableMajor",
    ":automergeBranch",           // Auto-merge to branch
    ":disableRateLimiting",       // No rate limits
    ":dependencyDashboard",       // Dashboard issue for tracking
  ],
}
```

### Custom Managers

Located in `.renovate/customManagers.json5`, these handle special update patterns like:

- Talos version updates
- Kubernetes version updates in Talos config
- Custom image references

### Grouping

Updates are grouped to reduce PR noise (`.renovate/groups.json5`):

- Related dependencies are updated together
- Major version updates may be grouped separately

## Update Types

### Helm Chart Updates

Helm charts are defined in HelmRelease resources:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: example
spec:
  chartRef:
    kind: OCIRepository
    name: example
```

Renovate updates the OCIRepository tag and Flux deploys the new version.

### Container Image Updates

Container images in deployments are automatically detected and updated:

```yaml
spec:
  containers:
    - name: app
      image: ghcr.io/example/app:v1.2.3  # Renovate updates this
```

### Talos and Kubernetes Versions

Version updates for Talos and Kubernetes are managed through:

- `talos/talconfig.yaml.j2` - Contains version references
- Custom Renovate managers detect and update these versions

## Dashboard

Renovate maintains a [Dependency Dashboard](https://github.com/hbjydev/phoebe/issues/9) issue that shows:

- Pending updates
- Awaiting merge PRs
- Ignored updates
- Update history

## Manual Updates

To manually trigger a Renovate run:

1. Go to the Renovate Dashboard issue
2. Check the "Rebase/retry this update" checkbox for specific PRs
3. Or wait for the next scheduled run

## Best Practices

1. **Review breaking changes** - Check changelogs in PRs before merging
2. **Monitor after merge** - Ensure Flux successfully reconciles
3. **Use the dashboard** - Track pending updates and ignored items
4. **Group wisely** - Related updates should deploy together

## Troubleshooting

### Update Not Appearing

- Check if the dependency is in `.renovaterc.json5` ignorePaths
- Verify the dependency manager is enabled
- Check the Dependency Dashboard for status

### Failed Deployments After Update

1. Check HelmRelease status: `kubectl get hr -A`
2. View Flux logs: `kubectl logs -n flux-system deployment/helm-controller`
3. Rollback by reverting the PR if needed
