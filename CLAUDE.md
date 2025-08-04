# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Phoebe is a GitOps repository for managing a bare metal Talos Kubernetes cluster. It uses Flux for continuous deployment and combines SOPS with 1Password for secret management. The repository structure follows a declarative approach where all cluster configuration is stored as code.

## Architecture

### Core Infrastructure Stack
- **Talos**: Immutable Kubernetes OS for bare metal deployment
- **Flux**: GitOps operator for continuous deployment from this repository
- **Cilium**: eBPF-based networking and L2 load balancing
- **Longhorn**: Distributed block storage system
- **External Secrets**: Manages Kubernetes secrets via 1Password Connect
- **Cert-manager**: Automated TLS certificate management via Let's Encrypt

### Directory Structure
- `kubernetes/`: All Kubernetes manifests organized by namespace and application
  - `apps/`: Application deployments grouped by namespace
  - `components/`: Reusable Kustomize components
  - `flux/`: Flux system configuration
- `talos/`: Talos configuration templates and node-specific configs
- `bootstrap/`: Initial cluster bootstrapping resources using Helmfile
- `scripts/`: Shell scripts for cluster management and deployment
- `terraform/`: Infrastructure as code for external resources

## Development Commands

### Cluster Management
```bash
# Bootstrap the cluster (requires KUBECONFIG and TALOSCONFIG)
./scripts/bootstrap.sh

# Apply Talos config to a node
just talos apply-node <ip> [machine_type] [mode]

# Generate kubeconfig for cluster access
just talos kubeconfig <ip>

# Sync Flux from Git repository
just flux sync

# Reconcile specific Kustomization
just flux sync-ks <kustomization_name> [namespace]
```

### Configuration Management
- Node configurations are generated from Jinja2 templates in `talos/`
- Kubernetes manifests use Kustomize for composition and templating
- Secrets are managed via SOPS encryption and External Secrets Operator
- Helm charts are deployed via HelmRelease resources managed by Flux

### Key Technologies
- **Just**: Command runner (replaces Make) - see Justfile for available commands
- **Helmfile**: Declarative Helm chart management for bootstrapping
- **Kustomize**: Native Kubernetes configuration management
- **SOPS**: Encrypted secrets safely stored in Git
- **Jinja2**: Templating for Talos machine configurations

## Secret Management
All secrets are encrypted with SOPS using Age encryption and stored in `kubernetes/components/common/sops/secret.sops.yaml`. The External Secrets Operator fetches secrets from 1Password Connect at runtime.

## Deployment Flow
1. Changes pushed to Git trigger Flux reconciliation
2. Flux applies Kustomizations in dependency order defined by Kustomization resources
3. Applications are deployed via HelmRelease resources
4. External Secrets injects sensitive data from 1Password
5. Cert-manager handles TLS certificate provisioning

This is a production homelab setup following cloud-native and GitOps best practices.