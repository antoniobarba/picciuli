#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu server for Picciuli. Run as root:
#
#   sudo bash bootstrap-vm.sh "ssh-ed25519 AAAA... github-actions-deploy"
#
# It installs Docker, a firewall, automatic security updates and the nightly
# backup, and creates the "deploy" user that GitHub Actions logs in as.
# Set HARDEN_SSH=1 to also disable SSH password logins (make sure your own
# key-based login works first!).
set -euo pipefail

deploy_user=${DEPLOY_USER:-deploy}
app_dir=${APP_DIR:-/opt/picciuli}
deploy_key=${1:?usage: bootstrap-vm.sh "<public SSH key of the deploy workflow>"}

if [[ $EUID -ne 0 ]]; then
    echo "run as root" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl sqlite3 unattended-upgrades \
    docker.io docker-compose-v2

# Only SSH and HTTP(S) are reachable from the internet. Oracle Cloud images
# filter with iptables (netfilter-persistent) instead of ufw: open the web
# ports in the saved rules, before their final REJECT.
if [[ -f /etc/iptables/rules.v4 ]]; then
    for rule in "-p tcp -m state --state NEW -m tcp --dport 80 -j ACCEPT" \
        "-p tcp -m state --state NEW -m tcp --dport 443 -j ACCEPT" \
        "-p udp -m udp --dport 443 -j ACCEPT"; do
        if ! grep -qF -- "-A INPUT $rule" /etc/iptables/rules.v4; then
            sed -i "0,/^-A INPUT -j REJECT/s//-A INPUT $rule\n&/" /etc/iptables/rules.v4
        fi
        # shellcheck disable=SC2086
        if ! iptables -C INPUT $rule 2>/dev/null; then
            reject=$(iptables -L INPUT --line-numbers | awk '$2 == "REJECT" {print $1; exit}')
            # shellcheck disable=SC2086
            iptables -I INPUT "${reject:-1}" $rule
        fi
    done
else
    apt-get install -y ufw
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow OpenSSH
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 443/udp
    ufw --force enable
fi
systemctl enable --now docker

# Rotate container logs instead of filling the disk.
if [[ ! -f /etc/docker/daemon.json ]]; then
    cat >/etc/docker/daemon.json <<'JSON'
{
  "log-driver": "local",
  "log-opts": { "max-size": "20m", "max-file": "5" }
}
JSON
    systemctl restart docker
fi

# Only SSH and HTTP(S) are reachable from the internet (see above).
dpkg-reconfigure -f noninteractive unattended-upgrades

# Deploy user: may run docker (which is root-equivalent: keep its key safe).
if ! id -u "$deploy_user" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$deploy_user"
fi
usermod -aG docker "$deploy_user"
home=$(getent passwd "$deploy_user" | cut -d: -f6)
install -d -m 700 -o "$deploy_user" -g "$deploy_user" "$home/.ssh"
touch "$home/.ssh/authorized_keys"
grep -qxF "$deploy_key" "$home/.ssh/authorized_keys" ||
    echo "$deploy_key" >>"$home/.ssh/authorized_keys"
chown "$deploy_user:$deploy_user" "$home/.ssh/authorized_keys"
chmod 600 "$home/.ssh/authorized_keys"

# Application directory; user databases belong to the container user (10001).
install -d -m 755 -o "$deploy_user" -g "$deploy_user" "$app_dir"
install -d -m 750 -o 10001 -g 10001 "$app_dir/data/picciuli"

cat >/etc/cron.d/picciuli-backup <<CRON
# Nightly backup of the Picciuli user databases and of Zitadel.
30 3 * * * root $app_dir/backup.sh >>/var/log/picciuli-backup.log 2>&1
CRON

if [[ ${HARDEN_SSH:-0} == 1 ]]; then
    cat >/etc/ssh/sshd_config.d/99-picciuli.conf <<'SSH'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
SSH
    systemctl reload ssh
fi

echo "Server ready. Next: copy deploy/.env.example to $app_dir/.env and fill it in."
