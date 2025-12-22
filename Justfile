set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

mod ansible "ansible"
mod bootstrap "bootstrap"
mod kube "kubernetes"
mod talos "talos"
mod terraform "terraform"

[private]
default:
    just -l

# Get Age key from 1Password
age:
  op read "op://cluster-phoebe/sops/SOPS_PRIVATE_KEY" > {{ justfile_directory() / "age.key" }}

[private]
log lvl msg *args:
  gum log -t rfc3339 -s -l "{{ lvl }}" "{{ msg }}" "{{ args }}"

[private]
template file *args:
  minijinja-cli "{{ file }}" {{ args }} | op inject
