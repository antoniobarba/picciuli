#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu server for Picciuli. Run as root from
# a directory that also holds picciuli-deploy and picciuli-deploy-ssh:
#
#   sudo bash bootstrap-vm.sh "ssh-ed25519 AAAA... github-actions-deploy"
#
# It installs Docker, a firewall, automatic security updates and the nightly
# backup, hardens SSH, and creates the "deploy" user that GitHub Actions logs
# in as. That user is not in the docker group: its key can only run
# "deploy <commit sha>" (see picciuli-deploy). Running it again is safe.
# Set HARDEN_SSH=1 to also disable SSH password logins (make sure your own
# key-based login works first!).
set -euo pipefail

deploy_user=${DEPLOY_USER:-deploy}
app_dir=${APP_DIR:-/opt/picciuli}
deploy_key=${1:?usage: bootstrap-vm.sh "<public SSH key of the deploy workflow>"}
script_dir=$(cd "$(dirname "$0")" && pwd)

if [[ $EUID -ne 0 ]]; then
    echo "run as root" >&2
    exit 1
fi
for unit in picciuli-backup.service picciuli-backup.timer; do
    if [[ ! -f $script_dir/$unit ]]; then
        echo "missing $script_dir/$unit: copy it next to bootstrap-vm.sh" >&2
        exit 1
    fi
done

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

# Nothing uses NFS: remove the RPC port mapper, which listens on port 111.
if dpkg -s rpcbind >/dev/null 2>&1; then
    systemctl disable --now rpcbind.socket rpcbind.service || true
    apt-get purge -y rpcbind
fi

# SSH: no X11 forwarding, fewer password/key attempts per connection. The
# drop-in sorts before the distribution's ones: sshd keeps the first value.
cat >/etc/ssh/sshd_config.d/10-picciuli-hardening.conf <<'SSH'
X11Forwarding no
MaxAuthTries 3
SSH
sshd -t
systemctl reload ssh

# Deploy user: not in the docker group (that would be root-equivalent). Its
# SSH key is restricted to the forced command picciuli-deploy-ssh, which may
# only run picciuli-deploy as root through sudo.
install -m 755 -o root -g root "$script_dir/picciuli-deploy" \
    "$script_dir/picciuli-deploy-ssh" /usr/local/sbin/
if ! id -u "$deploy_user" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$deploy_user"
fi
if id -nG "$deploy_user" | grep -qw docker; then
    gpasswd -d "$deploy_user" docker
fi
sudoers=$(mktemp)
echo "$deploy_user ALL=(root) NOPASSWD: /usr/local/sbin/picciuli-deploy" >"$sudoers"
visudo -cf "$sudoers"
install -m 440 -o root -g root "$sudoers" /etc/sudoers.d/picciuli-deploy
rm -f "$sudoers"
home=$(getent passwd "$deploy_user" | cut -d: -f6)
install -d -m 700 -o "$deploy_user" -g "$deploy_user" "$home/.ssh"
keys=$home/.ssh/authorized_keys
touch "$keys"
# Replace any earlier (unrestricted) line holding the same key.
grep -vF -- "$deploy_key" "$keys" >"$keys.new" || true
echo "command=\"/usr/local/sbin/picciuli-deploy-ssh\",restrict $deploy_key" >>"$keys.new"
mv "$keys.new" "$keys"
chown "$deploy_user:$deploy_user" "$keys"
chmod 600 "$keys"

# Application directory: owned by root, so that only picciuli-deploy changes
# the stack definition. User databases belong to the container user (10001).
install -d -m 755 -o root -g root "$app_dir"
install -d -m 750 -o 10001 -g 10001 "$app_dir/data/picciuli"

# Nightly backup of the user databases and of Zitadel with a systemd timer
# (cron is not installed on minimal images). backup.sh itself arrives with the
# first deployment.
for unit in picciuli-backup.service picciuli-backup.timer; do
    sed "s#/opt/picciuli#$app_dir#g" "$script_dir/$unit" >"/etc/systemd/system/$unit"
    chmod 644 "/etc/systemd/system/$unit"
done
rm -f /etc/cron.d/picciuli-backup
systemctl daemon-reload
systemctl enable --now picciuli-backup.timer

if [[ ${HARDEN_SSH:-0} == 1 ]]; then
    cat >/etc/ssh/sshd_config.d/99-picciuli.conf <<'SSH'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
SSH
    systemctl reload ssh
fi

echo "Server ready. Next: copy deploy/.env.example to $app_dir/.env and fill it in."
