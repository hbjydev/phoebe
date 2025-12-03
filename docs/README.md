---
title: Home
hide:
  - navigation
  - toc
---

#  <!-- To hide the main title -->

<div align="center" markdown>

<img src="https://avatars.githubusercontent.com/in/1354746?s=512" alt="A picture of Phoebe, one of the moons of Saturn" align="center" width="175px" height="175px" />

### Phoebe

_The cluster that runs on my desk, a bare metal Talos Kubernetes cluster, provisioned using `talosctl`, `helm`, and `flux`._

</div>


This site contains documentation for the cluster infrastructure running Phoebe,
the cluster that lives at my home.

It's a single-node* cluster running on semi-beefy hardware using Talos Linux
and Flux to give me a really clean workflow.

<sub>* for now</sub>

## Features

<div class="grid cards" markdown>

-   :simple-flux:{ .lg .middle} __Follows GitOps Principles__
      
    ---
    Syncs Kubernetes configuration from the GitHub repository with [Flux](./flows/gitops.md).

-   :simple-talos:{ .lg .middle } __Immutable OS__

    ---
    Uses an immutable base OS for security with [Talos Linux](./components/infrastructure/talos.md).

-   :octicons-upload-24:{ .lg .middle } __Continuous backups__

    ---

    Backs up continuously to S3-compatible storage with [Volsync](./flows/backups.md).

</div>

