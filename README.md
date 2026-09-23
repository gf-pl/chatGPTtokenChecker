# Codex Plan Monitor

A local dashboard for any number of ChatGPT accounts. Each card signs in through the official Codex device-code flow. The app reads the documented Codex App Server `account/rateLimits/read` and `account/usage/read` methods every few minutes and keeps snapshots in SQLite.

It shows remaining capacity and next reset time for five-hour and weekly windows, credit balance and available reset credits when reported, plan type, optional token activity, and a short local history. It never redeems a reset.

## Start

1. Pull or copy the project onto the machine that will run it.
2. Run `make deploy`. This creates `.env` from `.env.example` if needed, builds the image, starts the service, and waits for it to become healthy. Existing `.env` and saved account data are preserved.
3. Open `http://localhost:8090` on that machine, or use the configured `WEB_PORT`. The default `WEB_HOST=127.0.0.1` makes the page available only on that machine; use an SSH tunnel or a protected reverse proxy to view it remotely.
4. Select **Add account**, give the card a name, then select **Connect account** on the card. Enter the displayed code at the official sign-in page and choose the intended ChatGPT account. Repeat for each account.

Cards persist across restarts. On the first start after upgrading from the old two-account version, saved sign-ins and readings are imported as cards automatically. Account membership is managed on the page. The old API Admin keys are not used or passed to the container.

**Remove** deletes that card's local sign-in and saved readings after confirmation. The dashboard is bound to `127.0.0.1` by default and has no separate password. Keep the Docker `usage-data` volume private because it contains sign-in credentials. `REFRESH_INTERVAL_SECONDS` defaults to 300 and has a minimum of 60 seconds.

## Data coverage

- **Remaining capacity:** 100 minus the reported `usedPercent` in each quota window; it is a percentage, not a token or message count.
- **Next reset:** the reported `resetsAt` timestamp.
- **Available resets:** the reported reset-credit count, with titles and expiration when available.
- **Credits:** the account balance when reported by Codex.
- **History:** readings collected by this app after sign-in. Earlier usage and a complete record of past reset redemptions cannot be reconstructed.

Plan price and automatic top-up state are not returned by these App Server methods, so they are not displayed. The dashboard shows Codex and Work plan limits, not ordinary ChatGPT conversation message limits. It uses the documented [Codex App Server](https://learn.chatgpt.com/docs/app-server) account methods. OpenAI API organization Admin keys access a different billing and usage system.
