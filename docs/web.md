# Web and mobile app

`apps/web` is the graphical front-end of Picciuli: a web application that can
also be **installed** on a computer or a phone (a Progressive Web App). It has
the same screens as the [console interface](tui.md) and talks only to the
[API server](api-server.md), so every device sees the same data.

## Using it

Open the front-end address (in production `https://app.picciuli.party`), then
**Sign in** or **Create an account**. With native login enabled, sign-in,
registration, email verification, password recovery and authenticator codes
stay in Picciuli. Zitadel still stores identities, checks passwords and issues
tokens; Picciuli's confidential backend forwards credentials over HTTPS without
storing them. Existing accounts and their books are unchanged.

Registration requires email verification before the first sign-in. **Forgot
password?** sends a link back to Picciuli; opening an email link does not consume
its code until you submit the form. Required password changes and authenticator
setup are also handled in the app. Accounts requiring unsupported security keys
or SMS/email second factors are rejected rather than silently skipping MFA.

To install it:

- **Android (Chrome, Edge):** menu → *Install app* (or *Add to home screen*).
- **iPhone and iPad (Safari):** Share → *Add to Home Screen*.
- **Windows, macOS, Linux (Chrome, Edge):** the install icon in the address
  bar, or the account menu (top right) → *Install the app*.

The installed app opens in its own window, stays signed in (the login is
renewed silently, for up to 30 days, or 14 days without use) and updates
itself: when a new version is deployed, a banner offers to reload. It starts
without a network, but data is only read and written online; a banner says
when you are offline.

## Screens

On wide screens the tabs at the top switch screens; on phones the bar at the
bottom shows Overview, Accounts, Budgets and Investments, and **More** has the
rest. Every list row opens when clicked; its **⋯** menu has the other actions.
A category, period or budget opens its transactions with their total and what
is left of the budget (`e` or **⋯ › Edit** edits it); a transaction there opens
in the editor.
Every transaction list (the day's transactions, an account's register and the
category, period and budget dialogs) has a **Search transactions** box and
**Previous** / **Next** buttons, with 25 transactions per page. Search matches
words in descriptions, notes, accounts, categories, dates and amounts across
the whole list, not just the current page; clear it to see all transactions
again. Changing the day or account resets the search and page. In the
category, period and budget dialogs, the transaction count and **Total** cover
every page and narrow to the search results. Budget remaining, calendar figures
and the register's running balances always refer to the original full data,
regardless of search or page.
Accounts and categories are reordered by dragging the **⠿** handle at the
start of their row, with the mouse or a finger; a subcategory moves only among
the subcategories of the same parent, and a category takes its subcategories
along.

| Screen | What you can do |
|--------|-----------------|
| Overview | Month calendar with each day's net flow (`↔` = only transfers) and the selected period as a band; double-click a day to record a new transaction on it. The day's transactions; the period's categories against their budgets; balances and net worth at the end of the day, where a balance row opens that account's **register**. Swipe the calendar to change month on a phone. |
| Accounts | Accounts with balance, market value, goal and progress; create, edit, close or reopen, reorder (drag the handle) and delete. A row opens the **register** with running balances. |
| Categories | The two-level tree: create, edit, reorder (drag the handle), delete (moving the transactions of a category in use). A row shows the category's transactions (a top-level category includes its subcategories), their total and what is left of its budget in the period covering today. |
| Periods | Create, edit and delete periods. A row shows the transactions dated in the period, their net total and what is left of all its budgets. |
| Budgets | Budgets of a period with their progress; copy them from another period. A row shows the transactions of the budget's category (and subcategories, for a top-level one) in the period, their total and what is left. |
| Investments | Holdings at market value, securities and their latest prices; find a security online, buy, sell (with a preview of the cost basis and gain), enter prices, refresh prices, download the price history, live prices. |
| Settings | Currency, decimal digits, currency code, cost method and providers; export your data as a SQLite file (it opens with the console interface); import a SQLite file, such as the database of the console interface, choosing to **merge** it with your data or to **replace** your data; delete all your data, sign out. |

**Importing.** *Merge* reuses accounts, categories, securities and periods that
have the same name (securities also by ISIN, periods by their days) and skips
transactions identical to ones you already have, so importing the same file
twice adds nothing; your settings are kept and the file must use the same
currency and decimal digits (unless your book is still empty). *Replace*
deletes all your data first and adopts the file's settings. Either way the
import is all-or-nothing, and the file must follow the same rules as data
entered by hand (for example balanced transactions), otherwise nothing is
imported. Files from an older Picciuli version must be opened once with an
up-to-date console interface before they can be imported.

The transaction form has the four kinds of the console interface: **Expense**,
**Income**, **Transfer** and **Split**. In the split editor a live line shows
both totals, and the form refuses to save until they match. Editing a purchase
or sale of shares opens the **Buy shares** / **Sell shares** form instead, so
the quantity, cost or proceeds, paying or receiving account, fee, tax and
category can all be changed; saving rebuilds the transaction as a new trade
would (a sale's cost basis is computed again, ignoring the sale itself). A
trade whose splits were changed by hand opens in the split editor with its
quantities kept as they are.

Dates can be typed as `2025-02-03`, `3/2/2025`, `3/2`, `3`, `today`, `+7` or
`-30`, or picked with the calendar button. Amounts accept both `1,234.50` and
`1.234,50`; a single comma is a decimal separator (`12,50`).

## Keyboard

The keys of the console interface work on wide screens; press `?` for the full
list and `ctrl+k` for the command palette.

| Key | Action |
|-----|--------|
| `1` … `6`, `s` | Switch screen, settings |
| `n` / `e` / `d` | New / edit / delete the selected item |
| `shift+↑ ↓` | Move the selected account or category up / down |
| `alt+↑ ↓`; `space`, `↑ ↓`, `space` | On a focused **⠿** handle: move the row one step; or pick it up, choose its place and drop it (`esc` cancels) |
| `← → ↑ ↓`, `pgup` `pgdn`, `t`, `g` | Calendar: day, week, month, today, go to a date |
| `[` `]`, `p` | Previous / next period covering the day, start a period |
| `f`, `b`, `x`, `p`, `r`, `h`, `l` | Investments: find, buy, sell, price, refresh, history, live prices |
| `ctrl+s`, `esc` | Save / close a form |

## Development

```bash
cd apps/web
npm ci
npm run dev          # http://localhost:5173, against the production API and login
npm test             # unit and component tests (Vitest)
npm run lint && npm run typecheck
npm run build        # production files in dist/, without source maps
npm run api-types    # regenerate src/api/schema.d.ts after changing the API
```

Production builds do not publish source maps. To debug a local production
build, run `PICCIULI_SOURCEMAP=true npm run build`; never deploy that output.
`deepmerge`, a build-time dependency of the service-worker generator, has no
upstream fix for GHSA-gcqx-w48m-w2h4, so `vendor/deepmerge` holds a patched
copy that `package.json` substitutes through `overrides`. Drop it when
`workbox-build` no longer needs a vulnerable version.

`npm run dev` reads `.env.development`: it signs in through the Zitadel
application *Picciuli front-end (development)* (redirect URI
`http://localhost:5173/callback`) and reaches the API through the Vite proxy,
so the API does not need to allow the local origin. Set `PICCIULI_API_PROXY`
to use another API, or override any value in `.env.development.local`.

The code is organized as follows:

```
src/api/         typed client (openapi-fetch) and TanStack Query hooks;
                 schema.d.ts is generated from apps/api/openapi.json
src/auth/        native identity screens and OpenID Connect with PKCE
                 (oidc-client-ts); server operations are in picciuli_api/login.py
src/lib/         logic without components, ported from the console interface:
                 money.ts, dates.ts, calendar.ts, forms.ts, format.ts
src/components/  calendar, dialogs, form fields, menus
src/forms/       transaction, account, period and investment forms
src/screens/     one module per screen
src/app/         shell, routes, keyboard help, command palette, live prices
```

Amounts stay integers in minor units and quantities and prices stay decimal
strings, exactly as in the API, so no floating-point rounding ever happens.

### Token storage

The app is an OpenID Connect public client (Authorization Code with PKCE). It
keeps the access, ID and refresh tokens in `localStorage`, so an installed app
stays signed in between launches. Any script running in the page, through an
XSS bug or a malicious browser extension, could read them; a strict
Content-Security-Policy (`script-src 'self'`) and React's escaping are the
first line of defence, and the following limits bound what a stolen token is
worth:

- Access tokens (JWT) live one hour.
- Refresh tokens rotate on every use: a used one is rejected. They expire after
  14 days without use and 30 days after sign-in, whatever happens.
- Renewal happens on demand, one tab at a time (Web Locks), so tabs never
  present the same single-use refresh token twice.
- Sign-out revokes the access and refresh tokens at Zitadel and deletes them
  locally (native sign-out deletes them even when revocation fails). Tabs follow
  sign-in and sign-out in other tabs through `storage` events.

If a refresh token is stolen and used first, the attacker can keep renewing it
until the absolute expiry, and the legitimate app is signed out at its next
renewal. Sign-out on that device does not revoke the attacker's rotated token:
an administrator removes the user's sessions and tokens in the Zitadel console.

Alternatives considered:

- **Access token in memory, refresh token in `sessionStorage`.** An installed
  PWA loses `sessionStorage` when its window closes, so every launch would
  need a silent authorization through the identity provider. With native
  login that would need an iframe flow through `/login`, and every page would
  still be able to read the refresh token while the app is open, so the gain
  is small and the cost to users is a sign-in on most launches.
- **Backend-for-frontend with an HttpOnly cookie** (the native login already
  sets `__Host-picciuli-session` on the API). This keeps every token away from
  JavaScript and is the strongest option, but the API would have to hold the
  OIDC tokens server-side, proxy or authenticate every request by cookie,
  and add CSRF protection. It is the next step if the threat model changes.

## Deployment

The production image (`apps/web/Dockerfile`) contains only static files served
by Caddy. Its settings come from environment variables and reach the browser
as `/config.json`, so the same image works for every installation:

| Variable                   | Meaning                                     |
|----------------------------|---------------------------------------------|
| `PICCIULI_API_URL`         | API address, e.g. `https://api.example.com` |
| `PICCIULI_OIDC_ISSUER`     | Zitadel address                             |
| `PICCIULI_OIDC_CLIENT_ID`  | client id of the front-end application      |
| `PICCIULI_OIDC_PROJECT_ID` | Zitadel project id (the API's audience)     |
| `PICCIULI_NATIVE_LOGIN`   | `true` after the native backend and Zitadel application are configured; defaults to `false` |

The [deployment guide](deployment.md) explains how it is wired into the stack.

### Enabling native login

Roll out the images before switching the application's login URL. Hosted login
remains available for the Zitadel console and Swagger UI; do **not** replace
the instance-wide login URL.

1. Provision an `IAM_LOGIN_CLIENT` service-account PAT. The existing deployment's
   login-client PAT can be used; do not give the web application an administrator
   PAT. Install a copy as `/opt/picciuli/secrets/login-client.pat`, with directory
   mode `700`, file mode `400`, and owner `10001:10001` (the API container user).
   Neither this PAT nor the encryption key belongs in browser configuration.
2. Set the following in the server's `.env`:

   ```ini
   LOGIN_ORIGIN=https://app.example.com
   LOGIN_ORG_ID=<Zitadel organization resource ID, not project ID>
   PICCIULI_LOGIN_COOKIE_SECRET=<at least 32 random characters>
   NATIVE_LOGIN=true
   ```

   `WEB_CLIENT_ID` must identify the web application's OIDC client. Generate the
   independent cookie key with `openssl rand -base64 48`. Rotating it expires
   in-progress login flows and the native logout cookies.
3. Recreate the API/web containers and reload Caddy with the new stack
   definition. `/api/auth/*` must be proxied from the **web origin** to the API;
   the provided Caddy configuration does this. These are private browser
   endpoints, not part of the versioned book API or its generated OpenAPI client.
4. In **the web application's** Zitadel OIDC configuration, select Login V2 and
   set its custom base URI to `https://app.example.com/`. Zitadel appends
   `login?authRequest=...`, so do not append `/login` to the base URI. Keep
   authorization code, PKCE, refresh tokens and the existing `/callback` URI.
   The equivalent configuration is
   `loginVersion: { loginV2: { baseUri: "https://app.example.com/" } }`.

   The supplied stack initially **requires Login V2 instance-wide**. In Zitadel
   4.16 this also overrides application-specific base URIs, so the web app will
   still redirect to hosted login until that override is disabled. First
   explicitly configure the other OIDC applications (including the management
   console, Swagger and development clients) to use Login V2 with the existing
   hosted base URI, `https://auth.example.com/ui/v2/login/`, preserving their
   other settings. Then, authenticated as an administrator, update
   `PUT /v2/features/instance` with:

   ```json
   {
     "loginV2": {
       "required": false,
       "baseUri": "https://auth.example.com/ui/v2/login/"
     }
   }
   ```

   Keep the instance base URI unchanged; do not reset all instance features.
   This setting is persisted in Zitadel, separately from the server's `.env`.
   Configure future OIDC applications explicitly for Login V2 too. Verify that
   authorization for the web client redirects to `app.example.com/login`, while
   the console and other clients still redirect to hosted Login V2.
5. Keep registration and local password login enabled in the organization.
   Configure and test SMTP with a Picciuli sender name. New verification/reset
   messages use Picciuli links; already-sent messages keep their old links.
6. Verify registration, email delivery, password reset, MFA and sign-out before
   ending the rollout. Roll back by restoring the application's previous login
   base URI and setting `NATIVE_LOGIN=false`; do not remove the old Zitadel login
   container.

Login cookies are encrypted, HttpOnly, host-only, SameSite=Lax, and Secure on
HTTPS. Login flows expire after ten minutes; Zitadel sessions have a 30-day
lifetime. Session tokens never reach JavaScript. The OIDC access and refresh
tokens are kept as described in [Token storage](#token-storage). Native
sign-out terminates the current Zitadel session and revokes the app's tokens;
it does not sign out other devices.
Anonymous endpoints are limited to 30 requests per minute per client address
(IPv6: per /64), and guesses to 10 per 15 minutes per username, user ID and
Zitadel session, per API process. Native sign-in also requires a Zitadel lockout
policy (see [Account lockout and MFA](deployment.md#account-lockout-and-mfa)).
Keep the supplied single-process deployment or add a shared edge rate limiter
when scaling it.

For local native-login development, run the API with `PICCIULI_LOGIN_ORIGIN` set
to `http://localhost:5173`, the development client ID and the same server-only
organization/PAT/key settings. Point `PICCIULI_API_PROXY` at that API, set
`VITE_NATIVE_LOGIN=true` in `.env.development.local`, and set only the development
application's Login V2 base URI to `http://localhost:5173/`. HTTP cookies are
allowed only for localhost development. Never copy a PAT into a `VITE_*` variable.
