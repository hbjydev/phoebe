set default-list
set default-script
set no-exit-message
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

# Initialize a stack (downloads providers, configures the backend)
init stack *args:
  just terraform _run "{{ stack }}" init {{ args }}

# Show what a stack would change - always run this before apply
plan stack *args:
  just terraform _run "{{ stack }}" plan {{ args }}

# Apply a stack
[confirm('Apply Terraform changes to stack ' + stack + ' [y|N] ?')]
apply stack *args:
  just terraform _run "{{ stack }}" apply {{ args }}

# Import an existing resource into Terraform state
import stack address id:
  just terraform _run "{{ stack }}" import '{{ address }}' '{{ id }}'

# Validate a stack
validate stack *args:
  just terraform _run "{{ stack }}" validate {{ args }}

# Show the current state of a stack
show stack *args:
  just terraform _run "{{ stack }}" show {{ args }}

# Modify the current state of a stack
state stack *args:
  just terraform _run "{{ stack }}" state {{ args }}

# Format all Terraform files in place
fmt:
  terraform fmt -recursive "{{ source_directory() }}"

# Check formatting without writing
fmt-check:
  terraform fmt -check -recursive "{{ source_directory() }}"

# List available stacks
stacks:
  for d in "{{ source_directory() }}"/stacks/*/; do
    [[ -f "${d}main.tf" ]] || continue
    basename "$d"
  done

[private]
_stack-dir stack:
  dir="{{ source_directory() / 'stacks' / stack }}"
  [[ -d "$dir" ]] || just log fatal "No such stack" stack "{{ stack }}"
  echo "$dir"

[private]
_run stack *args:
  dir="$(just terraform _stack-dir {{ stack }})"
  cd "$dir"
  if [[ -f .env.op ]]; then
    op run --no-masking --env-file=.env.op -- terraform {{ args }}
  elif [[ -f terraform.tfvars.op ]]; then
    op inject --in-file terraform.tfvars.op --out-file=terraform.tfvars --force
    terraform {{ args }}
  else
    terraform {{ args }}
  fi
