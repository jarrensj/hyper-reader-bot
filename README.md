# Hyper Reader

Hyper Reader ([@hyperreader_bot](https://t.me/hyperreader_bot)) is a Telegram bot that alerts when BTC falls $1,000 or more within 60 seconds.

Prices come from the same oracle [Papertrade](https://docs.papertrade.xyz/) executes against: Hyperliquid's BBO precompile on HyperEVM (`0x000000000000000000000000000000000000080e`, asset `0` = BTC). The bot reads it with `eth_call` once a second and uses the bid/ask mid, exactly like Papertrade's `PriceOracle` (`0xa9B4c7b7Ca5835652d81E25739c870D49F39cC2e`).

## Commands

Send these in a DM with the bot or in a group it's been added to:

| Command | What it does |
| --- | --- |
| `/watch` | Start alerts in this chat |
| `/watch off` | Stop alerts in this chat |
| `/watch status` | Show whether this chat is watching, plus the current BTC price |

An alert looks like this:

```
🚨 BTC down $1,015 in 29s
$80,000.0 → $78,985.0
Hyperliquid BBO mid (Papertrade's execution price)
```

The bot also posts a warning if it can't read a price for 60s, and a message when it restarts.

## Configuration

Everything is set with environment variables.

| Variable | Default | Notes |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | required | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_ALLOWED_CHATS` | anyone | Comma-separated chat IDs. Commands from other chats are ignored. Chat IDs show up in the logs when someone sends `/watch`. |
| `ALERT_DROP_USD` | `1000` | Drop that triggers an alert, measured from the highest price in the window |
| `ALERT_WINDOW_SECONDS` | `60` | Lookback window |
| `ALERT_COOLDOWN_SECONDS` | `120` | Minimum time between alerts |
| `POLL_INTERVAL_SECONDS` | `1` | Time between price reads |
| `STATE_FILE` | `watchers.json` (`/data/watchers.json` in Docker) | Where the list of watching chats is saved |
| `HYPEREVM_RPC_URL` | `https://rpc.hyperliquid.xyz/evm` | Swap in a dedicated HyperEVM RPC if the public one rate-limits you |

## Getting a Telegram bot token

1. In Telegram, open a chat with [@BotFather](https://t.me/BotFather) and send `/newbot`.
2. Enter a display name (for example `Hyper Reader`), then a username that ends in `bot` (for example `hyperreader_bot`).
3. BotFather replies with a token that looks like `123456789:AAE...`. That's your `TELEGRAM_BOT_TOKEN`.

Treat the token like a password: anyone who has it can control the bot. Set it as an environment variable and never commit it to this repo. If it leaks, send `/revoke` to BotFather, pick the bot, and set the new token wherever the bot runs.

To use the bot in a group, add it as a member (group info → **Add members** → search the bot's username), then send `/watch` in the group. You don't need to change the bot's privacy settings; bots receive commands in groups either way.

## Production: Railway

Production runs as the `hyper-reader` service in the `hyper-reader` Railway project. It's a long-running worker with no web server or public URL; it long-polls Telegram for commands.

- Railway builds the `Dockerfile`, which sets `STATE_FILE=/data/watchers.json`.
- A volume is mounted at `/data`, so chats that ran `/watch` keep getting alerts after a redeploy.
- `TELEGRAM_BOT_TOKEN` is set on the service under **Variables** in the Railway dashboard. Changing a variable redeploys the service.

To deploy from a checkout of this repo:

```bash
railway link   # choose the hyper-reader project, then the hyper-reader service
railway up
```

Check that it's healthy with `railway logs`. Once a minute it logs the BTC price and how many chats are watching.

To set it up in a new Railway project instead:

```bash
railway init --name hyper-reader
railway add --service hyper-reader
railway service link hyper-reader
railway volume add --mount-path /data
```

Then add `TELEGRAM_BOT_TOKEN` under the service's **Variables** in the dashboard and run `railway up`.

## Running locally

Use this for development and testing. Use a **separate test bot** from @BotFather: if two copies of the bot run with the same token, they fight over Telegram updates (you'll see `409 Conflict` in the logs) and both send alerts.

Requires Python 3.8+. There are no dependencies to install.

1. Create a test bot and copy its token (see [Getting a Telegram bot token](#getting-a-telegram-bot-token)).
2. Run the bot:

   ```bash
   export TELEGRAM_BOT_TOKEN=<test bot token>
   python3 hyper_reader.py
   ```

3. Open a chat with the test bot in Telegram and send `/watch`. It replies with the current BTC price.

To see an alert without waiting for a real crash, lower the trigger:

```bash
ALERT_DROP_USD=20 ALERT_WINDOW_SECONDS=30 ALERT_COOLDOWN_SECONDS=30 python3 hyper_reader.py
```

Locally, the watching chats are saved to `watchers.json` in the current directory. Delete that file to reset them.
