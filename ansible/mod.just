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
