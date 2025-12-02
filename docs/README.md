# Phoebe Documentation

This directory contains documentation for the Phoebe GitOps cluster infrastructure.

## Contents

- [GitOps Flow](gitops-flow.md) - How changes get from Git to the cluster
- [Updates](updates.md) - How automatic updates work
- [Backups](backups.md) - How backups work
- [Talos Management](talos.md) - How Talos is managed and configured

## Quick Overview

Phoebe is a bare metal Talos Kubernetes cluster that uses GitOps principles for deployment and management. The infrastructure follows a declarative approach where:

1. **All configuration is stored as code** in this Git repository
2. **Flux** continuously reconciles the cluster state with the repository
3. **Renovate** automatically proposes updates via pull requests
4. **Volsync** handles persistent data backups to S3-compatible storage
5. **Talos** provides an immutable, secure Kubernetes OS foundation

For cluster bootstrapping instructions, see the main [README.md](../README.md).
