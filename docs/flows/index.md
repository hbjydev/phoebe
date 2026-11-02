# Workflows

These guides explain how the components work together to operate Phoebe.

The procedures identify commands that read state and commands that change it.
Read the prerequisites and stop conditions before running commands.

## Cluster workflows

- [GitOps](./gitops.md): Flux applies the configuration stored in Git to the cluster.
- [Updates](./updates.md): Renovate proposes dependency updates.
- [Backups](./backups.md): Inspect backup coverage and create a Kopiur backup.

## Restoration

Use [Restore an application](./restore-application.md) to restore a backup into a separate volume and plan the application switch.

Use [Restore PostgreSQL](./restore-postgres.md) to test database recovery in a separate cluster and plan the production switch.

## Maintenance

Use [Miroir maintenance](./maintenance.md) to reboot or shut down the node with its existing storage disk intact.
