# Workflows

These guides explain how the components work together to operate Phoebe.

## Cluster workflows

- [GitOps](./gitops.md): Flux applies the configuration stored in Git to the cluster.
- [Updates](./updates.md): Renovate proposes dependency updates.
- [Backups](./backups.md): Back up application data and restore volumes.

## Maintenance

The [Ceph maintenance runbook](./maintenance.md) describes how to stop
Ceph-backed workloads before maintenance and restore them in dependency order.

## Investigations

The [Ceph migration research](./ceph-migration-research.md) compares Miroir
and OpenEBS and plans a migration with the existing storage disk.
