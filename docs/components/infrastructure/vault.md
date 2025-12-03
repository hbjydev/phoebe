---
icon: simple/vault
---

# OpenBao/Vault

[OpenBao](https://openbao.org/) is an open-source fork of
[HashiCorp's Vault](https://developer.hashicorp.com/vault/docs/about-vault/what-is-vault?page=what-is-vault),
and is what I use to store all of my secrets used by the cluster and some of my
self-made applications.

It runs as a [virtual machine in UpCloud](../services/upcloud/virtual-machines.md),
primarily because I consider my secrets storage to be 'critical infrastructure',
meaning I can't tolerate the kinds of "uh oh I killed my server" failures that
could lead to data loss. I'm much happier to entrust that to a cloud provider.

## How does it get used?

OpenBao is mainly consumed by [External Secrets](../tools/external-secrets.md)
to sync secrets into Kubernetes as [`Secret` resources](https://kubernetes.io/docs/concepts/configuration/secret/),
which then get injected into containers that need them (a prime example being
[the S3 access keypair](https://github.com/hbjydev/phoebe/blob/main/kubernetes/components/volsync/externalsecret.yaml)
for [Volsync](../tools/volsync)).
