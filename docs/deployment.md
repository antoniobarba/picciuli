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

Copy the bootstrap script, the public key and the configuration template to the
server and run the script as root:

```bash
scp deploy/bootstrap-vm.sh deploy/.env.example picciuli-deploy.pub you@server:
ssh you@server
sudo bash bootstrap-vm.sh "$(cat picciuli-deploy.pub)"
sudo install -o deploy -g deploy -m 600 .env.example /opt/picciuli/.env
```

It installs Docker and the Compose plugin, opens only SSH, HTTP and HTTPS in the
server's firewall (ufw, or the iptables rules of Oracle Cloud images), enables
automatic security updates, log rotation and the nightly backup, and creates
the `deploy` user and `/opt/picciuli`. Run it again with `HARDEN_SSH=1` to
disable password logins once your own SSH key works.

!!! note "Cloud firewalls"
    Most clouds filter traffic before it reaches the server. On Oracle Cloud,
    open the web ports in the subnet's security list: *Networking → Virtual
    cloud networks → your VCN → Subnets → your subnet → Security → the
    security list → Add Ingress Rules*, source `0.0.0.0/0`, TCP destination
    ports `80,443`, and a second rule for UDP port `443` (HTTP/3, optional).

## 3. Configure the stack (once)

```bash
ssh you@server
sudo -u deploy -i
cd /opt/picciuli
nano .env
```

Fill in the domains, `ACME_EMAIL` and the secrets (the file explains how to
generate each one). Leave `OIDC_AUDIENCE` and `SWAGGER_CLIENT_ID` empty for
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
first deployment let the server pull them:

```bash
# as the deploy user, with a classic token that has only read:packages
echo <token> | docker login ghcr.io -u antoniobarba --password-stdin
```

(Alternatively, after the first push make the packages public: **Packages →
picciuli-api** (and **picciuli-web**) **→ Package settings → Change
visibility**. The Deploy workflow pushes the images before waiting for your
approval, so a new package can be made public before approving.)

Then run the **Deploy** workflow (**Actions → Deploy → Run workflow**) or push
to `master`. The first start of Zitadel takes a minute or two.

## 5. Set up Zitadel (once)

Open `https://auth.example.com/ui/console` and log in as `admin` with the
password from `.env`.

1. **Project.** *Projects → Create*, name it `Picciuli`. Copy its **Resource
   Id**: this is `OIDC_AUDIENCE`.
2. **Application for Swagger UI.** In the project,
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
5. **Self-registration.** *Default settings → Login behavior and security*:
   enable **Register allowed**. Under *Password complexity* and *Lockout* pick
   your rules; enable passkeys or OTP under *Login behavior* if you like.
6. **E-mail.** *Default settings → SMTP provider*: add an SMTP server (your
   mail provider, Brevo, Mailgun, Amazon SES...) so that Zitadel can verify
   addresses and send password resets.

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

and apply them with `./deploy.sh <current tag>` (or just re-run the workflow).

## 6. Check

- `https://api.example.com/healthz` answers `{"status":"ok"}`;
- `https://api.example.com/docs` → **Authorize** → log in → try `GET /api/v1/me`;
- `https://app.example.com` → **Sign in** shows the overview; `www` and the
  bare domain redirect to it;
- register a second user from the login page and check that they see an empty
  book.

## Everyday operations

**Deploy:** push to `master`. CI runs lint, type checks and tests, builds and
smoke-tests the image; then the Deploy workflow ships it.

**Roll back:** run the Deploy workflow by hand with the commit SHA of a previous
image, or on the server:

```bash
cd /opt/picciuli && ./deploy.sh <commit sha>
```

**Logs:** `docker compose logs -f api` (or `web`, `zitadel-api`, `caddy`).

**Upgrade Zitadel:** change `ZITADEL_VERSION` in `.env` after reading its
release notes, back up first, then `./deploy.sh <current tag>`.

**Backups:** `backup.sh` runs every night at 03:30 (see
`/etc/cron.d/picciuli-backup`). It writes
`/var/backups/picciuli/<timestamp>.tar.gz` with a consistent copy of every user
database and a dump of Zitadel, and keeps 14 days. Backups on the same disk do
not survive the loss of the server: set `RESTIC_REPOSITORY` and
`RESTIC_PASSWORD` (plus the credentials of the storage, e.g. Backblaze B2 or a
Hetzner Storage Box) in the cron file and install `restic` to keep an
encrypted off-site copy. Test a restore from time to time.

**Restore one user:** find their file name with `GET /api/v1/me` (`id` field),
stop the API (`docker compose stop api`), copy
`users/<id>.db` from the archive into `data/picciuli/users/`, fix the owner
(`chown 10001:10001`), then `docker compose start api`. Users can also download
their own data at any time with `GET /api/v1/me/export`.

**Restore Zitadel:** `docker compose exec -T postgres pg_restore -U postgres
--clean -d zitadel < zitadel.dump` with the same `ZITADEL_MASTERKEY`.
