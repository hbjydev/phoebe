set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

# Install Ansible collections required for VPS playbook
install-collections:
  ansible-galaxy collection install -r "{{ source_directory() / "requirements.yaml" }}"

# Run Ansible playbook on a given IP address
[confirm("Run playbook on " + ip + " [y|N]?")]
run ip: install-collections
  ansible-playbook -i "{{ ip }}," "{{ source_directory() / "playbook.yaml" }}"

# Trigger a doco-cd deployment via the API
[confirm('Trigger doco-cd deployment on ' + ip + ' [y|N] ?')]
deploy ip:
    api_key=$(vals get "ref+op://cluster-phoebe/app-doco-cd/apiSecret") && \
    curl --silent --fail --request POST \
      --url 'https://doco-cd.hayden.moe/v1/api/poll/run?wait=true' \
      --header 'content-type: application/json' \
      --header "x-api-key: ${api_key}" \
      --data '[{\"url\": \"https://git.hayden.moe/hayden/phoebe.git\"}]'
