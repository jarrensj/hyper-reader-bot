#!/usr/bin/env python3
"""Hyper Reader: Telegram bot that alerts on sharp BTC drops, priced off Papertrade's oracle.

Papertrade's PriceOracle reads Hyperliquid's BBO precompile on HyperEVM
(0x...080e) and executes at the bid/ask mid. This bot makes the same read via
eth_call, tracks the highest mid over each alert tier's trailing window, and
alerts the chats on that tier when the current mid falls far enough below it.

Telegram commands:
  /watch          start alerts in this chat (normal tier)
  /watch off      stop alerts in this chat
  /watch status   show this chat's tier, plus the current price

Environment:
  TELEGRAM_BOT_TOKEN       required, from @BotFather
  TELEGRAM_ALLOWED_CHATS   optional comma-separated chat IDs; commands from other chats are ignored
  NORMAL_DROP_USD          normal tier: USD drop that triggers an alert (default 1000)
  NORMAL_WINDOW_SECONDS    normal tier: lookback window in seconds (default 60)
  ALERT_COOLDOWN_SECONDS   min seconds between alerts in a tier (default 120)
  POLL_INTERVAL_SECONDS    seconds between price reads (default 1)
  STATE_FILE               where watching chats are saved (default watchers.json)
  HYPEREVM_RPC_URL         HyperEVM RPC (default https://rpc.hyperliquid.xyz/evm)
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime
from types import SimpleNamespace

RPC_URL = os.environ.get("HYPEREVM_RPC_URL", "https://rpc.hyperliquid.xyz/evm")
BBO_PRECOMPILE = "0x000000000000000000000000000000000000080e"
BTC_ASSET = 0  # HyperCore perp index; BTC = 0 on chain 999
BTC_PX_SCALE = 10  # precompile prices carry 6 - szDecimals(5) = 1 decimal
FEED_DOWN_AFTER = 60  # seconds of failed reads before alerting that the feed is down

# Each watching chat is on one tier: name -> (USD drop, lookback window in seconds).
# Override a tier with <NAME>_DROP_USD and <NAME>_WINDOW_SECONDS.
TIER_DEFAULTS = {"normal": (1000, 60)}
DEFAULT_TIER = "normal"
TIERS = {
    name: (
        float(os.environ.get(f"{name.upper()}_DROP_USD", drop)),
        float(os.environ.get(f"{name.upper()}_WINDOW_SECONDS", window)),
    )
    for name, (drop, window) in TIER_DEFAULTS.items()
}
COOLDOWN_SECONDS = float(os.environ.get("ALERT_COOLDOWN_SECONDS", 120))
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL_SECONDS", 1))
STATE_FILE = os.environ.get("STATE_FILE", "watchers.json")


def trigger(tier):
    drop, window = TIERS[tier]
    return f"${drop:,.0f} drop within {window:.0f}s"


HELP = (
    "Hyper Reader: BTC drop alerts, priced off Hyperliquid's BBO mid (the price Papertrade executes at).\n\n"
    + "".join(f"/watch{'' if t == DEFAULT_TIER else ' ' + t} - alert on a {trigger(t)}\n" for t in TIERS)
    + "/watch off - stop alerts\n"
    "/watch status - show this chat's tier and the current price"
)


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


class HTTPStatusError(RuntimeError):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status


def post_json(url, payload, timeout=10):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Telegram puts the useful part ("Unauthorized", "chat not found", ...) in the body.
        raise HTTPStatusError(e.code, e.read().decode(errors="replace")[:300]) from None


def read_bbo(asset=BTC_ASSET, scale=BTC_PX_SCALE):
    """Return (bid, ask, mid) in USD, with the same sanity checks as PriceOracle."""
    call = {"to": BBO_PRECOMPILE, "data": "0x" + asset.to_bytes(32, "big").hex()}
    resp = post_json(RPC_URL, {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [call, "latest"]})
    if "error" in resp:
        raise RuntimeError(f"rpc error: {resp['error']}")
    raw = bytes.fromhex(resp["result"][2:])
    if len(raw) < 64:
        raise RuntimeError(f"short precompile result: {resp['result']}")
    bid = int.from_bytes(raw[:32], "big")
    ask = int.from_bytes(raw[32:64], "big")
    if bid == 0 or ask == 0 or ask < bid:
        raise RuntimeError(f"zero or crossed book: bid={bid} ask={ask}")
    return bid / scale, ask / scale, (bid + ask) / 2 / scale


class DropDetector:
    """Fires when the price sits `drop` or more below the high of the last `window` seconds."""

    def __init__(self, drop, window, cooldown):
        self.drop = drop
        self.window = window
        self.cooldown = cooldown
        # (ts, price) with strictly decreasing prices, so the front is the window high.
        self.samples = deque()
        self.last_alert = float("-inf")

    def update(self, ts, price):
        """Record a price; return (seconds_since_high, high) if an alert should fire."""
        while self.samples and self.samples[-1][1] <= price:
            self.samples.pop()
        self.samples.append((ts, price))
        while self.samples[0][0] < ts - self.window:
            self.samples.popleft()
        high_ts, high = self.samples[0]
        if high - price >= self.drop and ts - self.last_alert >= self.cooldown:
            self.last_alert = ts
            return ts - high_ts, high
        return None


class Watchers:
    """Tier for each chat with /watch on, saved to disk so it survives restarts."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.tiers = {}
        try:
            with open(path) as f:
                saved = json.load(f)
        except FileNotFoundError:
            return
        except ValueError as e:
            log(f"ignoring unreadable {path}: {e}")
            return
        if isinstance(saved, list):  # saved before tiers existed: a list of chat IDs
            saved = {chat_id: DEFAULT_TIER for chat_id in saved}
        self.tiers = {int(chat_id): tier for chat_id, tier in saved.items() if tier in TIERS}

    def tier(self, chat_id):
        with self.lock:
            return self.tiers.get(chat_id)

    def chats(self, tier=None):
        """Chats on `tier`, or every watching chat when tier is None."""
        with self.lock:
            return sorted(chat_id for chat_id, t in self.tiers.items() if tier in (None, t))

    def set(self, chat_id, tier):
        """Put the chat on `tier`, or stop its alerts when tier is None."""
        with self.lock:
            if tier:
                self.tiers[chat_id] = tier
            else:
                self.tiers.pop(chat_id, None)
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.tiers, f)
            os.replace(tmp, self.path)


class Telegram:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method, http_timeout=10, **params):
        resp = post_json(self.base + method, params, http_timeout)
        if not resp.get("ok"):
            raise RuntimeError(f"{method}: {resp}")
        return resp["result"]

    def send(self, chat_id, text):
        for attempt in range(1, 4):
            try:
                self.call("sendMessage", chat_id=chat_id, text=text)
                return
            except Exception as e:
                log(f"send to {chat_id} failed (attempt {attempt}/3): {e}")
                time.sleep(2 * attempt)


def broadcast(tg, chat_ids, text):
    # One thread per chat so a dead chat's retries don't delay everyone else.
    for chat_id in chat_ids:
        threading.Thread(target=tg.send, args=(chat_id, text), daemon=True).start()


def price_line(latest):
    if latest.mid is None:
        return "BTC price not available yet"
    age = time.monotonic() - latest.at
    stale = f" (stale, {age:.0f}s old)" if age > 10 else ""
    return f"BTC ${latest.mid:,.1f}{stale}"


def handle_command(text, chat_id, bot_username, watchers, latest):
    """Return the reply to a command message, or None if it isn't one of ours."""
    parts = text.split()
    command, _, target = parts[0].lower().partition("@")
    if target and target != bot_username.lower():
        return None  # addressed to another bot in the group
    if command in ("/start", "/help"):
        return HELP
    if command != "/watch":
        return None

    arg = parts[1].lower() if len(parts) > 1 else "on"
    tier = DEFAULT_TIER if arg == "on" else arg
    if tier in TIERS:
        watchers.set(chat_id, tier)
        return (
            f"Watching BTC on the {tier} tier. I'll alert here on a {trigger(tier)}.\n"
            f"{price_line(latest)}\nSend /watch off to stop."
        )
    if arg == "off":
        watchers.set(chat_id, None)
        return "Stopped BTC alerts in this chat. Send /watch to turn them back on."
    if arg == "status":
        tier = watchers.tier(chat_id)
        state = f"ON, {tier} tier ({trigger(tier)})" if tier else "OFF"
        return f"Alerts: {state}\n{price_line(latest)}"
    return HELP


def run_bot(tg, bot_username, watchers, latest, allowed):
    offset = 0
    while True:
        try:
            updates = tg.call("getUpdates", http_timeout=40, offset=offset, timeout=30, allowed_updates=["message"])
        except Exception as e:
            # A 409 Conflict here means another copy of the bot is polling with the same token.
            log(f"getUpdates failed: {e}")
            time.sleep(5)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message") or {}
            text, chat = msg.get("text", ""), msg.get("chat")
            if not chat or not text.startswith("/"):
                continue
            label = f"chat {chat['id']} ({chat.get('title') or chat.get('username') or chat.get('first_name')})"
            if allowed and chat["id"] not in allowed:
                log(f"ignoring {text!r} from {label}: not in TELEGRAM_ALLOWED_CHATS")
                continue
            try:
                reply = handle_command(text, chat["id"], bot_username, watchers, latest)
                if reply:
                    log(f"{text!r} from {label}")
                    tg.send(chat["id"], reply)
            except Exception as e:
                log(f"handling {text!r} from {label} failed: {e}")


def run_price_loop(tg, watchers, latest):
    detectors = {tier: DropDetector(drop, window, COOLDOWN_SECONDS) for tier, (drop, window) in TIERS.items()}
    first_failure = None
    feed_down_sent = False
    next_status = 0.0
    while True:
        started = time.monotonic()
        try:
            _, _, mid = read_bbo()
        except Exception as e:
            first_failure = first_failure or started
            log(f"price read failed: {e}")
            if not feed_down_sent and started - first_failure >= FEED_DOWN_AFTER:
                broadcast(tg, watchers.chats(), f"⚠️ BTC price feed DOWN for {FEED_DOWN_AFTER}s, alerts paused. Last error: {e}")
                feed_down_sent = True
            time.sleep(max(POLL_INTERVAL, 5))
            continue
        if feed_down_sent:
            broadcast(tg, watchers.chats(), f"BTC price feed recovered, alerts resumed. {price_line(latest)}")
        first_failure, feed_down_sent = None, False
        latest.mid, latest.at = mid, started

        for tier, detector in detectors.items():
            hit = detector.update(started, mid)
            if hit:
                secs, high = hit
                chats = watchers.chats(tier)
                text = (
                    f"🚨 BTC down ${high - mid:,.0f} in {secs:.0f}s\n"
                    f"${high:,.1f} → ${mid:,.1f}\n"
                    "Hyperliquid BBO mid (Papertrade's execution price)"
                )
                log(f"{tier} ALERT to {len(chats)} chat(s): {text!r}")
                broadcast(tg, chats, text)
        if started >= next_status:
            counts = ", ".join(f"{len(watchers.chats(t))} {t}" for t in TIERS)
            log(f"BTC mid ${mid:,.1f}, chats watching: {counts}")
            next_status = started + 60

        time.sleep(max(0.0, POLL_INTERVAL - (time.monotonic() - started)))


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and set its token.")
    allowed = {int(c) for c in os.environ.get("TELEGRAM_ALLOWED_CHATS", "").replace(",", " ").split()}

    tg = Telegram(token)
    # Wait out network blips here instead of exiting, so they don't burn Railway's restart retries.
    while True:
        try:
            bot_username = tg.call("getMe")["username"]
            tg.call("setMyCommands", commands=[{"command": "watch", "description": "BTC drop alerts: /watch, /watch off, /watch status"}])
            break
        except Exception as e:
            if isinstance(e, HTTPStatusError) and e.status in (401, 404):
                sys.exit(f"Telegram rejected TELEGRAM_BOT_TOKEN: {e}")
            log(f"Telegram startup call failed, retrying in 10s: {e}")
            time.sleep(10)

    watchers = Watchers(STATE_FILE)
    latest = SimpleNamespace(mid=None, at=0.0)
    tiers = ", ".join(f"{t} = {trigger(t)}" for t in TIERS)
    log(f"@{bot_username} up: tiers {tiers}, via BBO precompile on {RPC_URL}")
    log(f"{len(watchers.chats())} chat(s) watching, state in {STATE_FILE}")
    if allowed:
        log(f"only accepting commands from chats {sorted(allowed)}")
    broadcast(tg, watchers.chats(), "Hyper Reader restarted. Still watching BTC here. Send /watch status to see your tier.")

    threading.Thread(target=run_bot, args=(tg, bot_username, watchers, latest, allowed), daemon=True).start()
    run_price_loop(tg, watchers, latest)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
