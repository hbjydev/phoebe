# GitOps Flow

This document explains how changes get from Git to the Kubernetes cluster.

## Overview

Phoebe uses [Flux](https://fluxcd.io) as its GitOps operator. Flux continuously monitors the Git repository and automatically applies changes to the cluster when they are committed to the `main` branch.

## Architecture

```
┌─────────────────┐    push     ┌──────────────┐    sync    ┌─────────────┐
│   Developer     │ ─────────► │   GitHub     │ ◄───────── │    Flux     │
│   (You!)        │            │   Repository │            │  (Cluster)  │
└─────────────────┘            └──────────────┘            └─────────────┘
                                                                  │
                                                                  ▼
                                                           ┌─────────────┐
                                                           │ Kubernetes  │
                                                           │  Resources  │
                                                           └─────────────┘
```

## How It Works

### 1. Git Repository as Source of Truth

The Git repository (`hbjydev/phoebe`) is the single source of truth for the cluster state. All Kubernetes manifests, Helm releases, and configurations are stored in the `kubernetes/` directory.

### 2. Flux Components

Flux runs inside the cluster and consists of several controllers:

- **Source Controller**: Fetches manifests from the Git repository
- **Kustomize Controller**: Applies Kustomizations and manages dependencies
- **Helm Controller**: Deploys applications via HelmRelease resources
- **Notification Controller**: Handles alerting and external notifications

### 3. Reconciliation Loop

1. Flux polls the Git repository (default interval: 1 hour, configurable per resource)
2. When changes are detected, Flux pulls the latest manifests
3. The Kustomize Controller applies resources in dependency order
4. HelmReleases are reconciled by the Helm Controller
5. External Secrets injects sensitive data from 1Password

### 4. SOPS Decryption

Encrypted secrets (using SOPS with Age encryption) are automatically decrypted at apply time:

```yaml
spec:
  decryption:
    provider: sops
    secretRef:
      name: sops-age
```

## Directory Structure

```
kubernetes/
├── apps/           # Application deployments by namespace
│   ├── cert-manager/
│   ├── flux-system/
│   ├── kube-system/
│   └── ...
├── components/     # Reusable Kustomize components
│   ├── common/
│   ├── postgres/
│   ├── redis/
│   └── volsync/
└── flux/           # Flux system configuration
    └── cluster/
        └── ks.yaml # Root Kustomization
```

## Kustomization Hierarchy

The root Kustomization at `kubernetes/flux/cluster/ks.yaml` points to `kubernetes/apps/`, which contains per-namespace Kustomizations. Dependencies between applications are defined using `dependsOn`:

```yaml
spec:
  dependsOn:
    - name: external-secrets
```

## Manual Sync

To force an immediate sync (useful for debugging), use the Just commands:

```bash
# Sync all GitRepositories
just kube sync-git

# Sync all Kustomizations
just kube sync-ks

# Sync all HelmReleases
just kube sync-hr

# Sync all OCIRepositories
just kube sync-oci
```

## Deployment Workflow

1. **Make changes** to manifests in the repository
2. **Create a PR** for review (Renovate does this automatically for dependency updates)
3. **Merge to main** - Flux will automatically detect and apply the changes
4. **Monitor** - Check Flux logs or use `kubectl get ks -A` to verify reconciliation

## Troubleshooting

### Check Kustomization Status

```bash
kubectl get kustomizations -A
```

### View Flux Logs

```bash
kubectl logs -n flux-system deployment/kustomize-controller
```

### Check HelmRelease Status

```bash
kubectl get helmreleases -A
```

### Force Immediate Reconciliation

```bash
just kube sync-ks
```
