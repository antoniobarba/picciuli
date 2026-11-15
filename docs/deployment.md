# Deployment

The production stack runs on one Linux server with Docker Compose:

| Service         | Role                                                         |
|-----------------|--------------------------------------------------------------|
| `caddy`         | HTTPS reverse proxy; gets Let's Encrypt certificates itself  |
| `api`           | the Picciuli API (image built by GitHub Actions)             |
| `web`           | the web front-end: static files (image built by GitHub Actions) |
| `zitadel-api`   | identity provider: users, registration, login, MFA          |
| `zitadel-login` | Zitadel's login pages                                        |
| `postgres`      | Zitadel's database (not reachable from outside)              |

Every push to `master` runs CI; when it passes, the **Deploy** workflow builds
the API and web images from the same commit, pushes them to GitHub Container
Registry (`ghcr.io`) and updates the server over SSH. The user databases live
in `/opt/picciuli/data/picciuli/users` and are backed up every night.

## 1. Domain name

You need a domain with three names pointing to the server (plus, optionally,
`www` and the bare domain, which redirect to the front-end):

| Name                | Used by                       |
|---------------------|-------------------------------|
| `api.example.com`   | the API (and its `/docs`)     |
| `auth.example.com`  | Zitadel (login, registration) |
| `app.example.com`   | the web front-end             |

Cheap and trustworthy registrars:

- **Cloudflare Registrar**: sells domains at cost (about 10 €/year for a
  `.com`) with free DNS. Recommended.
- **Porkbun**: similar prices, free DNS, simple interface.

Prefer `.com`, `.eu`, `.it` or `.dev` over "1 € the first year" extensions,
which often renew at much higher prices. In the registrar's DNS panel create
`A` records (and `AAAA` if the server has IPv6) for `api`, `auth` and `app`
pointing to the server's public address. If you use Cloudflare, set them to
**DNS only** (grey cloud) so that Caddy can get the certificates.

## 2. Prepare the server (once)

On your computer, create the key GitHub Actions will use to log in:

```bash
ssh-keygen -t ed25519 -N "" -C picciuli-deploy -f picciuli-deploy
```

Copy the bootstrap script, the backup timer, the two deploy scripts, the
public key and the configuration template to the server and run the script as
root:

```bash
scp deploy/bootstrap-vm.sh deploy/picciuli-backup.service \
  deploy/picciuli-backup.timer deploy/picciuli-deploy deploy/picciuli-deploy-ssh \
  deploy/.env.example picciuli-deploy.pub you@server:
ssh you@server
sudo bash bootstrap-vm.sh "$(cat picciuli-deploy.pub)"
sudo install -o root -g root -m 600 .env.example /opt/picciuli/.env
```

It installs Docker and the Compose plugin, opens only SSH, HTTP and HTTPS in the
server's firewall (ufw, or the iptables rules of Oracle Cloud images), enables
automatic security updates, log rotation and the nightly backup timer,
removes the unused RPC port mapper (`rpcbind`), sets `X11Forwarding no` and
`MaxAuthTries 3` for SSH, and creates `/opt/picciuli` (owned by root) and the
`deploy` user. That user is **not** in the `docker` group: its key may only run
`deploy <commit sha>` (see [Deploy user](#deploy-user)). Run the script again
with `HARDEN_SSH=1` to disable password logins once your own SSH key works;
running it again is safe.

!!! note "Cloud firewalls"
    Most clouds filter traffic before it reaches the server. On Oracle Cloud,
    open the web ports in the subnet's security list: *Networking → Virtual
    cloud networks → your VCN → Subnets → your subnet → Security → the
    security list → Add Ingress Rules*, source `0.0.0.0/0`, TCP destination
    ports `80,443`, and a second rule for UDP port `443` (HTTP/3, optional).

## 3. Configure the stack (once)

```bash
ssh you@server
sudo nano /opt/picciuli/.env
```

Fill in the domains, `ACME_EMAIL`, the secrets (the file explains how to
generate each one) and `LOGIN_CLIENT_PAT_EXPIRATION` (at most a year ahead).
Leave `OIDC_AUDIENCE` and `SWAGGER_CLIENT_ID` empty for
now: until then the API is up but rejects every token. **Store a copy of
`.env` in your password manager**: the Zitadel master key cannot be recovered.

## 4. Connect GitHub (once)

In the repository, **Settings → Secrets and variables → Actions**:

| Kind     | Name                 | Value                                         |
|----------|----------------------|-----------------------------------------------|
| secret   | `DEPLOY_SSH_KEY`     | content of the private key `picciuli-deploy`  |
| secret   | `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan <server address>`      |
| variable | `DEPLOY_HOST`        | server address                                |
| variable | `DEPLOY_USER`        | `deploy`                                      |
| variable | `API_DOMAIN`         | `api.example.com`                             |
| variable | `APP_DOMAIN`         | `app.example.com` (smoke test of the front-end) |

Create a `production` environment (**Settings → Environments**) with yourself
as required reviewer to approve each deployment, and protect the `master`
branch (**Settings → Branches**): only commits pushed to `master` of this
repository are ever deployed.

The images are pushed to `ghcr.io/antoniobarba/picciuli-api` and
`ghcr.io/antoniobarba/picciuli-web`, which are private by default. Before the
first deployment let the server pull them (deployments run as root):

```bash
# with a classic token that has only read:packages
echo <token> | sudo docker login ghcr.io -u antoniobarba --password-stdin
```

(Alternatively, after the first push make the packages public: **Packages →
picciuli-api** (and **picciuli-web**) **→ Package settings → Change
visibility**. The Deploy workflow pushes the images before waiting for your
approval, so a new package can be made public before approving.)

Then run the **Deploy** workflow (**Actions → Deploy → Run workflow**) or push
to `master`. The first start of Zitadel takes a minute or two.

## 5. Set up Zitadel (once)

Open `https://auth.example.com/ui/console` and log in as `admin` with the
password from `.env`. Zitadel asks you to choose a new password at this first
login (the one in `.env` is then useless: replace it there with a random
value); also set up a second factor for `admin` (*Personal information → Multi-factor authentication*).

1. **Project.** *Projects → Create*, name it `Picciuli`. Copy its **Resource
   Id**: this is `OIDC_AUDIENCE`.
2. **Application for Swagger UI** (optional: Swagger UI is only served with
   `DOCS_ENABLED=true`, see [Security](#security)). In the project,
   *New → User Agent → PKCE*. Redirect URI:
   `https://api.example.com/docs/oauth2-redirect`. Copy the **Client Id**:
   this is `SWAGGER_CLIENT_ID`.
3. **Application for the web front-end.** Again *New → User Agent → PKCE*,
   named e.g. *Picciuli front-end*: redirect URI
   `https://app.example.com/callback`, post-logout URI
   `https://app.example.com/`, grant types **Authorization Code** and
   **Refresh Token** (so that the app stays signed in). Its **Client Id** is
   `WEB_CLIENT_ID`. For local development add a second application with
   **Development mode** on and the URIs `http://localhost:5173/callback` and
   `http://localhost:5173/`.
4. In the **Token Settings** of each application, set **Auth Token Type** to
   **JWT**. The API validates JWT access tokens; opaque tokens are rejected.

   Then limit the token lifetimes, which Zitadel sets for the whole instance:
   *Default settings → OIDC Token lifetimes and expiration*:

   | Setting                          | Value     | Zitadel default |
   |----------------------------------|-----------|-----------------|
   | Access Token Lifetime            | 1 hour    | 12 hours        |
   | ID Token Lifetime                | 12 hours  | 12 hours        |
   | Refresh Token Idle Expiration    | 14 days   | 30 days         |
   | Refresh Token Expiration         | 30 days   | 90 days         |

   or, with an administrator's access token,
   `PUT https://auth.example.com/admin/v1/settings/oidc` with
   `{"accessTokenLifetime": "3600s", "idTokenLifetime": "43200s",
   "refreshTokenIdleExpiration": "1209600s", "refreshTokenExpiration":
   "2592000s"}` (all four fields are required), and check the result with
   `GET` on the same address. Zitadel always rotates refresh tokens and rejects
   a used one; there is nothing to enable. Users whose refresh token is older
   than the new limits sign in once more. See
   [Token storage](web.md#token-storage) for the reasoning.
5. **Self-registration.** *Default settings → Login behavior and security*:
   enable **Register allowed**. Under *Password complexity* pick your rules;
   enable passkeys or OTP under *Login behavior* if you like.
6. **Lockout (required).** Without a lockout policy, Zitadel allows unlimited
   password and authenticator-code guesses, and the API refuses native sign-in
   (see [Account lockout](#account-lockout-and-mfa)). Once the PAT and `.env`
   values of [native login](web.md#enabling-native-login) are in place, copy
   `deploy/zitadel_security.py` to `/opt/picciuli` and run:

   ```bash
   cd /opt/picciuli
   sudo python3 zitadel_security.py lockout --apply   # 5 passwords, 5 OTPs
   sudo python3 zitadel_security.py status
   ```

   `status` must show `maxPasswordAttempts` and `maxOtpAttempts` of 5 with
   `RESOURCE_OWNER_TYPE_ORG`. Alternatively set them in the console under
   *Organization → Settings → Lockout*.
7. **E-mail.** *Default settings → SMTP provider*: add an SMTP server (your
   mail provider, Brevo, Mailgun, Amazon SES...) so that Zitadel can verify
   addresses and send password resets. Test delivery and activate the provider
   before inviting users: without an active provider, the login UI can ask for
   a verification code even though no email can be delivered.

   For **Resend**, first verify your sending domain using the DNS records
   supplied by Resend, then configure:

   | Setting | Value |
   |---------|-------|
   | SMTP host | `smtp.resend.com:587` |
   | TLS (STARTTLS) | Enabled |
   | Username | `resend` |
   | Password | Your Resend API key |
   | Sender address | `noreply@<your verified domain>` |
   | Sender name | `Picciuli` |

   Enter the key only in Zitadel's SMTP credentials; never commit it. Zitadel
   stores the provider in its database, so no application redeploy is needed.
   After testing and activating it, use **Resend code** on the login page.

Put the values in `/opt/picciuli/.env`:

```bash
OIDC_AUDIENCE=<project resource id>
SWAGGER_CLIENT_ID=<client id of the Swagger UI application>
SWAGGER_SCOPES=openid profile email urn:zitadel:iam:org:project:id:<project resource id>:aud
WEB_CLIENT_ID=<client id of the front-end application>
CORS_ORIGINS=https://app.example.com
```

The `urn:zitadel:iam:org:project:id:<id>:aud` scope makes Zitadel put the
project id in the token's audience; the front-end requests it too.

and apply them with `sudo ./deploy.sh <current tag>` (or just re-run the workflow).

## 6. Check

- `https://api.example.com/healthz` answers `{"status":"ok"}`, and
  `https://api.example.com/docs` answers 404 (unless `DOCS_ENABLED=true`);
- `https://app.example.com` → **Sign in** shows the overview; `www` and the
  bare domain redirect to it;
- register a second user from the login page and check that they see an empty
  book.

## Account lockout and MFA

The organization's lockout policy locks a user after 5 wrong passwords or 5
wrong authenticator codes. The API checks it before every native sign-in step
(re-reading it every five minutes): while the policy is missing or zero, native
sign-in answers `503` and the API logs `has no lockout policy`. Setting
`PICCIULI_LOGIN_REQUIRE_LOCKOUT=false` keeps sign-in available and only logs
the error; use it only temporarily. On top of Zitadel's lockout, the API allows
30 requests per minute per client address (an IPv6 /64 counts as one address)
and 10 attempts per 15 minutes per username, user ID and Zitadel session.

A locked user stays locked until an administrator unlocks them: in the console
(*Users → user → Unlock*) or with `POST /v2/users/<id>/unlock`. Anyone who
knows an email address can lock that account, including the administrator's,
so keep a second administrator (or the console session) available. The demo
reset unlocks the `demo` user automatically.

**MFA is optional** for now: users who enrolled an authenticator app must use
it, others sign in with a password. Requiring MFA protects every account
against password reuse, and is recommended for a financial app, but every user
without an authenticator is asked to enrol one at their next sign-in (and the
administrator must enrol one before using the console or `zitadel_security.py`
again). After warning the users, run:

```bash
cd /opt/picciuli
sudo python3 zitadel_security.py force-mfa           # shows the change
sudo python3 zitadel_security.py force-mfa --apply
```

Undo it in the console (*Organization → Settings → Login behavior → Force
MFA*).

## Everyday operations

**Demo account:** the opt-in `deploy/reset_demo.py` operator script keeps a
provisioned `demo` identity and resets its password and book. Store its numeric
Zitadel ID and approved password in `/opt/picciuli/secrets/demo.json` as
`{"user_id": "<id>", "password": "<password>"}` (mode `600`, owner UID `10001`).
Never commit this file. The script refuses identities outside the configured
organization or with a username other than `demo`.

Install the script as `/opt/picciuli/demo/reset_demo.py`, together with the
existing TUI `demo.py` and `calendar_model.py` modules in
`/opt/picciuli/demo/picciuli_tui/`. Run it using the deployed API image:

```bash
cd /opt/picciuli
sudo docker compose run --rm --no-deps -T \
  -v /opt/picciuli/demo:/demo:ro -e PYTHONPATH=/demo \
  --entrypoint python api /demo/reset_demo.py
```

This uses the current UTC date for the demo periods and SQLite's online backup
API to replace only the pinned user's data atomically. It does not unlink an
open database or restart the production API. Password changes and database
replacement are separate operations; failures exit nonzero and must be checked
by the operator or scheduler. Installing the script alone does not schedule it.

To enable resets every ten minutes (`:00`, `:10`, ..., `:50` UTC), install
`deploy/picciuli-demo-reset.service` and `deploy/picciuli-demo-reset.timer` in
`/etc/systemd/system/` with mode `644`, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now picciuli-demo-reset.timer
systemctl list-timers picciuli-demo-reset.timer
sudo journalctl -u picciuli-demo-reset.service --no-pager -n 30
```

The timer survives reboot and catches up a missed run. Systemd prevents
overlapping scheduled runs; a reset is limited to three minutes and its named
one-off container is cleaned up afterward. Failures remain visible in the
service status and journal. Stop automatic resets with
`sudo systemctl disable --now picciuli-demo-reset.timer`.

**Deploy:** push to `master`. CI retains lint, type checks, coverage, frontend
tests/build and strict documentation validation. Python tests run on the
production runtime (Linux 3.13), the library minimum (Linux 3.10), and Windows
3.14 rather than every OS/version combination. Pull requests additionally build
and smoke-test both images; master avoids repeating those image builds before
Deploy. Production images are built natively on ARM64 (not emulated or also
built for unused AMD64) and the deployed services are health-checked. Stale CI
runs are cancelled; production deployments are not.

To move sign-in and registration into Picciuli, follow
[Enabling native login](web.md#enabling-native-login). It is a per-application
rollout; keep the hosted Zitadel interface for administration.

**Roll back:** run the Deploy workflow by hand with the full SHA of a previous
commit of `master`, or on the server:

```bash
sudo /usr/local/sbin/picciuli-deploy <full commit sha>   # that commit's stack and images
cd /opt/picciuli && sudo ./deploy.sh <commit sha>        # only that commit's images
```

**Logs:** `sudo docker compose logs -f api` (or `web`, `zitadel-api`, `caddy`).

**Upgrade Zitadel:** the version and image digests are pinned in
`deploy/compose.yml` (Dependabot proposes updates). Read the release notes,
back up first, then merge the update to `master`.

**Backups:** `picciuli-backup.timer` runs `backup.sh` every night at 03:30 UTC
(and catches up after downtime). It writes
`/var/backups/picciuli/<timestamp>.tar.gz` (mode `600`, root only) with a
consistent copy of every user database and a dump of Zitadel, and keeps 14
days. The service logs to the journal and fails if no archive newer than 26
hours exists afterwards; before each run it also warns if a night was missed.

```bash
systemctl list-timers picciuli-backup.timer
sudo journalctl -u picciuli-backup.service --no-pager -n 30
sudo systemctl start picciuli-backup.service   # back up now
sudo /opt/picciuli/backup.sh --check           # exit 1 if older than 26 h
```

On servers prepared before the timer existed, install it by hand: copy
`deploy/picciuli-backup.service` and `deploy/picciuli-backup.timer` to
`/etc/systemd/system/` (mode `644`), remove `/etc/cron.d/picciuli-backup`, then
`sudo systemctl daemon-reload && sudo systemctl enable --now
picciuli-backup.timer`.

**Off-site copy (restic):** backups on the same disk do not survive the loss of
the server. To keep an encrypted off-site copy:

1. Create a storage bucket or account (e.g. Backblaze B2, a Hetzner Storage
   Box or any S3-compatible service) and an access key limited to it.
2. On the server, `sudo apt-get install -y restic`.
3. Create `/etc/picciuli/backup.env` (owner root, mode `600`; directory mode
   `700`) with `RESTIC_REPOSITORY`, `RESTIC_PASSWORD` and the storage
   credentials (e.g. `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` or
   `B2_ACCOUNT_ID`/`B2_ACCOUNT_KEY`). The service reads it automatically.
   Keep a copy of `RESTIC_PASSWORD` outside the server: without it the copies
   cannot be decrypted.
4. Initialise the repository once:
   `sudo sh -c 'set -a; . /etc/picciuli/backup.env; restic init'`.
5. `sudo systemctl start picciuli-backup.service` and check that
   `restic snapshots --tag picciuli` (with the same environment) lists it.

**Test a restore** from time to time, without touching the live data:

```bash
t=$(sudo mktemp -d)
sudo tar -C "$t" -xzf "$(sudo ls -t /var/backups/picciuli/*.tar.gz | head -n 1)"
sudo sh -c "for db in $t/*/users/*.db; do sqlite3 \$db 'PRAGMA integrity_check;'; done"
sudo sh -c "cat $t/*/zitadel.dump" |
  (cd /opt/picciuli && sudo docker compose exec -T postgres pg_restore --list) | head
sudo rm -rf "$t"
```

**Restore one user:** find their file name with `GET /api/v1/me` (`id` field),
stop the API (`sudo docker compose stop api`), copy
`users/<id>.db` from the archive into `data/picciuli/users/`, fix the owner
and mode (`chown 10001:10001` and `chmod 600`), then
`sudo docker compose start api`. Users can also download
their own data at any time with `GET /api/v1/me/export`, and load it back
with `POST /api/v1/me/import?mode=replace`.

**Restore Zitadel:** `sudo docker compose exec -T postgres pg_restore -U postgres
--clean -d zitadel < zitadel.dump` with the same `ZITADEL_MASTERKEY`.

## Security

### Containers

`deploy/compose.yml` gives every service a memory, CPU and process limit
(`mem_limit`, `cpus`, `pids_limit`, sized well above normal use: check with
`sudo docker stats --no-stream`), drops all Linux capabilities except the few
it needs (`NET_BIND_SERVICE` for Caddy; the ownership/user-switching ones for
Postgres's entrypoint), and sets `no-new-privileges`. The API and web
containers have a read-only root filesystem (the API writes only to `/data`
and a 128 MB `/tmp`). Nothing runs as root except Caddy and Postgres's
entrypoint: the API as uid 10001 with umask 077 (user databases are `0600`),
Zitadel as uid 1000 (its `zitadel-bootstrap` volume belongs to it) and the
login UI as its image's `nextjs` user. Zitadel reads its master key from the
environment (`--masterkeyFromEnv`), so it never appears in `ps`.

The `web` network has a fixed subnet (`172.30.0.0/24`) and Caddy the fixed
address `172.30.0.10`, the only peer the API trusts for `X-Forwarded-For`
(`PICCIULI_FORWARDED_ALLOW_IPS`): the login rate limiter keys on it.

### HTTP

Caddy sends `Strict-Transport-Security` (one year, subdomains) on every site
and removes the `Server` header. The API site also sends
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and, under
`/api/`, `Cache-Control: no-store`. Request bodies above 1 MB are rejected with
413 before they reach the API, except `/api/v1/me/import`, which accepts up to
50 MB (the API's `PICCIULI_MAX_IMPORT_BYTES`; change both together). The web
front-end's own headers (CSP etc.) come from `apps/web/Caddyfile`.

Swagger UI, ReDoc and `/openapi.json` are off in production. To use them for
a while, set `DOCS_ENABLED=true` in `.env` and redeploy (`sudo ./deploy.sh
<current tag>`); the schema is also in the repository
(`apps/api/openapi.json`).

### Deploy user

GitHub Actions logs in as `deploy`, whose key is restricted in
`~deploy/.ssh/authorized_keys` to the forced command
`/usr/local/sbin/picciuli-deploy-ssh`. That only accepts `deploy <full commit
sha>` and runs `/usr/local/sbin/picciuli-deploy` through sudo (the only sudo
rule of `deploy`, in `/etc/sudoers.d/picciuli-deploy`). The root-owned
`picciuli-deploy` checks with the GitHub API that the commit is on `master`,
downloads that commit's `deploy/compose.yml`, `Caddyfile`, `deploy.sh`,
`backup.sh` and `.env.example`, installs them root-owned in `/opt/picciuli`
and runs `deploy.sh`. A stolen deploy key can therefore only redeploy a commit
of `master`; it is not in the `docker` group and cannot run anything else.
`picciuli-deploy` and `picciuli-deploy-ssh` are installed by
`bootstrap-vm.sh`: after changing them, copy them to the server and run it
again (or `sudo install -m 755 picciuli-deploy picciuli-deploy-ssh
/usr/local/sbin/`). A new file needed on the server must be added to the list
in `picciuli-deploy`.

### Supply chain

Actions are pinned to commit SHAs, base and service images to digests of their
multi-platform index, and the API image's Python packages to the hashed
`apps/api/requirements*.lock`; Dependabot proposes updates
(see [Development](development.md#pinned-dependencies)).

### Rotating secrets

**Login client PAT.** The `login-client` service user's personal access token
lets the login UI and the API's native login act for any user. It expires on
the date in Zitadel (the first one from `LOGIN_CLIENT_PAT_EXPIRATION`): rotate
it at least a month before, and update `LOGIN_CLIENT_PAT_EXPIRATION` in `.env`
to the new date as a reminder. On the server, with the current token (which
may create and delete its own tokens):

```bash
cd /opt/picciuli
old=$(sudo cat secrets/login-client.pat)
api=https://auth.example.com
id=$(curl -sS -H "Authorization: Bearer $old" $api/auth/v1/users/me |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["user"]["id"])')
# list the tokens (note the id of the current one)
curl -sS -X POST -H "Authorization: Bearer $old" -H 'Content-Type: application/json' \
  $api/v2/users/pats/search -d "{\"filters\":[{\"userIdFilter\":{\"id\":\"$id\"}}]}"
# create the new one
new=$(curl -sS -X POST -H "Authorization: Bearer $old" -H 'Content-Type: application/json' \
  $api/v2/users/$id/pats -d '{"expirationDate":"2028-11-15T00:00:00Z"}' |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
# install it for the API (read at every call) and the login UI (read at start)
vol=$(sudo docker volume inspect picciuli_zitadel-bootstrap -f '{{.Mountpoint}}')
printf '%s\n' "$new" | sudo install -m 400 -o 10001 -g 10001 /dev/stdin secrets/login-client.pat
printf '%s\n' "$new" | sudo install -m 644 -o 1000 -g 1000 /dev/stdin "$vol/login-client.pat"
sudo docker compose restart zitadel-login
# check that https://auth.example.com/ui/v2/login/loginname loads, then delete the old token
curl -sS -X DELETE -H "Authorization: Bearer $new" $api/v2/users/$id/pats/<old token id>
unset old new
```

If the token has already expired, create the new one in the console instead
(*Users → Service Users → login-client → Personal Access Tokens → New*, as
`admin`), then install it in both places as above.

**Admin password.** Change it in the console (*Personal information →
Password*) whenever someone who knew it leaves, and keep MFA enabled. The
`ZITADEL_ADMIN_PASSWORD` in `.env` is only used on the very first start.

**Master key.** `ZITADEL_MASTERKEY` cannot be rotated: keep `.env` (mode
`600`, owned by root) and its copy in the password manager safe.

### Upgrading an existing server

Servers prepared before this setup need these one-time steps (done on
production on 2026-11-15), before the first deployment with the new workflow:

```bash
# Zitadel runs as uid 1000; the user databases become private
vol=$(sudo docker volume inspect picciuli_zitadel-bootstrap -f '{{.Mountpoint}}')
sudo chown -R 1000:1000 "$vol"
sudo chmod 700 /opt/picciuli/data/picciuli/users
sudo find /opt/picciuli/data/picciuli/users -type f -exec chmod 600 {} +
echo 'LOGIN_CLIENT_PAT_EXPIRATION=<expiry of the current PAT>' | sudo tee -a /opt/picciuli/.env
# restricted deploy user, root-owned stack, host hardening
sudo bash bootstrap-vm.sh "$(cat picciuli-deploy.pub)"
sudo chown root:root /opt/picciuli /opt/picciuli/.env /opt/picciuli/*.yml \
  /opt/picciuli/Caddyfile /opt/picciuli/*.sh /opt/picciuli/.env.example
```

The first `up` with the new `compose.yml` recreates the `web` network (fixed
subnet), restarting every container once.
