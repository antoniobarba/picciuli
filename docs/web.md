# Web and mobile app

`apps/web` is the graphical front-end of Picciuli: a web application that can
also be **installed** on a computer or a phone (a Progressive Web App). It has
the same screens as the [console interface](tui.md) and talks only to the
[API server](api-server.md), so every device sees the same data.

## Using it

Open the front-end address (in production `https://app.picciuli.party`), then
**Sign in** or **Create an account**. Logins are handled by Zitadel; the app
never sees your password.

To install it:

- **Android (Chrome, Edge):** menu → *Install app* (or *Add to home screen*).
- **iPhone and iPad (Safari):** Share → *Add to Home Screen*.
- **Windows, macOS, Linux (Chrome, Edge):** the install icon in the address
  bar, or the account menu (top right) → *Install the app*.

The installed app opens in its own window, stays signed in (the login is
renewed silently) and updates itself: when a new version is deployed, a banner
offers to reload. It starts without a network, but data is only read and
written online; a banner says when you are offline.

## Screens

On wide screens the tabs at the top switch screens; on phones the bar at the
bottom shows Overview, Accounts, Budgets and Investments, and **More** has the
rest. Every list row opens when clicked; its **⋯** menu has the other actions.

| Screen | What you can do |
|--------|-----------------|
| Overview | Month calendar with each day's net flow (`↔` = only transfers) and the selected period as a band; the day's transactions; the period's categories against their budgets; balances and net worth at the end of the day. Swipe the calendar to change month on a phone. |
| Accounts | Accounts with balance, market value, goal and progress; create, edit, close or reopen, reorder and delete. A row opens the **register** with running balances. |
| Categories | The two-level tree: create, edit, reorder, delete (moving the transactions of a category in use). |
| Periods | Create, edit and delete periods. |
| Budgets | Budgets of a period with their progress; copy them from another period. |
| Investments | Holdings at market value, securities and their latest prices; find a security online, buy, sell (with a preview of the cost basis and gain), enter prices, refresh prices, download the price history, live prices. |
| Settings | Currency, decimal digits, currency code, cost method and providers; export your data as a SQLite file (it opens with the console interface), delete all your data, sign out. |

The transaction form has the four kinds of the console interface: **Expense**,
**Income**, **Transfer** and **Split**. In the split editor a live line shows
both totals, and the form refuses to save until they match. Purchases and
sales of shares open in the split editor with their quantities kept as they
are.

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
npm run build        # production files in dist/
npm run api-types    # regenerate src/api/schema.d.ts after changing the API
```

`npm run dev` reads `.env.development`: it signs in through the Zitadel
application *Picciuli front-end (development)* (redirect URI
`http://localhost:5173/callback`) and reaches the API through the Vite proxy,
so the API does not need to allow the local origin. Set `PICCIULI_API_PROXY`
to use another API, or override any value in `.env.development.local`.

The code is organized as follows:

```
src/api/         typed client (openapi-fetch) and TanStack Query hooks;
                 schema.d.ts is generated from apps/api/openapi.json
src/auth/        OpenID Connect login with PKCE (oidc-client-ts)
src/lib/         logic without components, ported from the console interface:
                 money.ts, dates.ts, calendar.ts, forms.ts, format.ts
src/components/  calendar, dialogs, form fields, menus
src/forms/       transaction, account, period and investment forms
src/screens/     one module per screen
src/app/         shell, routes, keyboard help, command palette, live prices
```

Amounts stay integers in minor units and quantities and prices stay decimal
strings, exactly as in the API, so no floating-point rounding ever happens.

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

The [deployment guide](deployment.md) explains how it is wired into the stack.
