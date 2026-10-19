# Guide

This section of the site documents what _workflows_ are happening inside my
cluster. This goes one step higher than the Components section by mapping out
what my cluster is _doing_ with the components installed.

## Runbooks

- [Ceph maintenance](./maintenance.md) - Quiesce Ceph-backed workloads before
  planned storage or node maintenance, then restore them in dependency order.

## Investigations

- [Ceph migration research](./ceph-migration-research.md) - Compare Miroir and
  OpenEBS and plan a migration using the existing storage disk.
