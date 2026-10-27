#!/usr/bin/env sh
# Explicit fresh-runtime setup from Docker's official Ubuntu apt repository.
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Run this optional runtime installer with sudo.' >&2; exit 1; }
. /etc/os-release
[ "$ID" = ubuntu ] || { echo 'This helper supports Ubuntu only; use your platform Docker Engine installation.' >&2; exit 1; }
if command -v docker >/dev/null 2>&1; then
    docker compose version
    echo 'Existing Docker installation preserved.'
    exit 0
fi
for task_package in docker.io docker-compose podman-docker containerd runc; do
    if dpkg-query -W -f='${Status}' "$task_package" 2>/dev/null | grep -q 'install ok installed'; then
        echo "Existing $task_package installation found. Resolve package conflicts using Docker documentation before installing." >&2
        exit 1
    fi
done
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
if [ ! -f /etc/apt/sources.list.d/docker.sources ]; then
    cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
fi
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl start docker
docker info >/dev/null
docker compose version
echo 'Docker Engine and Compose are ready. Run PrintFlow setup with suitable Docker socket access.'
