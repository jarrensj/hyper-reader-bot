# Hyper Oracle

Hyper Oracle is a Telegram bot that alerts when BTC falls $1,000 or more within 60 seconds.

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

## Production: Railway

The bot runs on Railway as a long-running worker. It has no web server or public URL; it long-polls Telegram for commands.

- `Dockerfile` builds the image and sets `STATE_FILE=/data/watchers.json`.
- `railway.json` uses the Dockerfile and restarts the service whenever it exits.
- A volume is mounted at `/data`, so chats that ran `/watch` keep getting alerts after a redeploy.

Set `TELEGRAM_BOT_TOKEN` (and any other variables) on the service under **Variables** in the Railway dashboard. Changing a variable redeploys the service.

To deploy code changes from this directory:

```bash
railway up
```

Check that it's healthy with `railway logs`. Once a minute it logs the BTC price and how many chats are watching.

## Running locally

Use this for development and testing. Use a **separate test bot** from @BotFather: if two copies of the bot run with the same token, they fight over Telegram updates (you'll see `409 Conflict` in the logs) and both send alerts.

Requires Python 3.8+. There are no dependencies to install.

1. Create a test bot with @BotFather (`/newbot`) and copy its token.
2. Run the bot:

   ```bash
   export TELEGRAM_BOT_TOKEN=<test bot token>
   python3 hyper_oracle.py
   ```

3. Open a chat with the test bot in Telegram and send `/watch`. It replies with the current BTC price.

To see an alert without waiting for a real crash, lower the trigger:

```bash
ALERT_DROP_USD=20 ALERT_WINDOW_SECONDS=30 ALERT_COOLDOWN_SECONDS=30 python3 hyper_oracle.py
```

Locally, the watching chats are saved to `watchers.json` in the current directory. Delete that file to reset them.
