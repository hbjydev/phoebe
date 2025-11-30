set shell := ["bash", "-euo", "pipefail", "-c"]
set quiet := true

terraform_dir := justfile_dir() + "/terraform"
op_run        := "op run --env-file=" + terraform_dir + "/.env.op"
plan_file     := terraform_dir + "/plan.tfplan"

[private]
default:
  just -l terraform

# Plans infrastructure changes, but does not apply them.
plan *args:
  {{op_run}} -- terraform plan -out={{ plan_file }} {{ args }}

# Applies infrastructure changes as specified in the most recent plan.
apply *args:
  {{op_run}} -- terraform apply {{ plan_file }} {{ args }}

# Imports existing infrastructure into Terraform.
import res id *args:
  {{op_run}} --no-masking -- terraform import {{ res }} {{ id }} {{ args }}

# Initializes the Terraform working directory.
init *args:
  op read "op://cluster-phoebe/talos/certs-k8sserviceaccount/key" \
    | base64 -d \
    | openssl rsa -pubout > {{ terraform_dir }}/jwtca.pub && \
  {{op_run}} -- terraform init {{ args }}

# Works with State
state *args:
  {{op_run}} -- terraform state {{ args }}
