set shell := ["bash", "-euo", "pipefail", "-c"]
set quiet := true

terraform_dir := justfile_dir() + "/terraform"
op_run        := "op run --env-file=" + terraform_dir + "/.env.op"
plan_file     := terraform_dir + "/plan.tfplan"

[private]
default:
  just -l terraform

[private]
run *args:
  cmd=""; \
  if [[ "${CI:-false}" != "true" ]]; then \
    cmd="{{op_run}} -- "; \
  fi; \
  ${cmd}terraform {{ args }}

# Plans infrastructure changes, but does not apply them.
plan *args:
  just terraform run plan -out={{ plan_file }} {{ args }}

# Applies infrastructure changes as specified in the most recent plan.
apply *args:
  just terraform run apply {{ plan_file }} {{ args }}

# Works with State
state *args:
  just terraform run state {{ args }}

# Imports existing infrastructure into Terraform.
import res id *args:
  just terraform run import {{ res }} {{ id }} {{ args }}

# Initializes the Terraform working directory.
init *args:
  jwtca_pub="${K8SSERVICEACCOUNT_KEY:-}"; \
  if [[ "${CI:-false}" != "true" ]]; then \
    jwtca_pub="$(op read 'op://cluster-phoebe/talos/certs-k8sserviceaccount/key')"; \
  fi; \
  echo "$jwtca_pub" | base64 -d | openssl rsa -pubout > {{ terraform_dir }}/jwtca.pub && \
  just terraform run init {{ args }}

sync-secrets:
  echo "$(cat {{ terraform_dir }}/.env.op | sed 's/^#.*$//' | op inject)" | gh secret set -f -
