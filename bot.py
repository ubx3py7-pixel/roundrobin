import os
import asyncio
import subprocess
import signal
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, ConversationHandler, filters
)
from playwright.async_api import async_playwright

# ================= CONFIG =================
BOT_TOKEN = "8264209354:AAGUBDHsLpir61C3CTiQFz6_cWVBWOrczAI"

SESSION_FILE = "ig_session.json"
SESSIONID_FILE = "sessionid.txt"
MESSAGE_FILE = "m.txt"

MAX_SESSION_RETRIES = 3
RETRY_DELAY = 6  # seconds

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1280, "height": 800}

ASK_MESSAGE, ASK_GC = range(2)

sender_process = None
live_task = None
total_sent = 0
# =========================================


# 🔐 SESSION CREATION (AUTO RETRY + CHECKPOINT DETECT)
async def create_session(sessionid: str, notify=None):
    for attempt in range(1, MAX_SESSION_RETRIES + 1):
        try:
            if notify:
                await notify(f"🔐 Session attempt {attempt}/{MAX_SESSION_RETRIES}")

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=False,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )

                context = await browser.new_context(
                    user_agent=DESKTOP_UA,
                    viewport=VIEWPORT
                )

                await context.add_cookies([{
                    "name": "sessionid",
                    "value": sessionid,
                    "domain": ".instagram.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                }])

                page = await context.new_page()
                await page.goto("https://www.instagram.com/", timeout=60000)

                await page.wait_for_selector("body", timeout=30000)
                await asyncio.sleep(5)

                url = page.url.lower()

                if ("login" in url or "checkpoint" in url or "challenge" in url):
                    raise Exception("CHECKPOINT_OR_EXPIRED")

                logged = await page.query_selector('a[href="/direct/inbox/"]')
                if not logged:
                    raise Exception("NOT_LOGGED_IN")

                await context.storage_state(path=SESSION_FILE)
                await browser.close()

                if notify:
                    await notify("✅ Session created successfully")
                return True

        except Exception:
            if attempt == MAX_SESSION_RETRIES:
                if notify:
                    await notify("❌ Session failed (expired / checkpoint)")
                if os.path.exists(SESSION_FILE):
                    os.remove(SESSION_FILE)
                return False

            await asyncio.sleep(RETRY_DELAY)

    return False


# ================= BOT =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome 🤗 to multi gc spam Bot⛈️{Use this cmds to control bot }\n\n"
        "/session <sessionid>\n"
        "/send\n"
        "/stop"
    )


async def set_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Usage: /session <sessionid>")
        return

    sessionid = context.args[0]
    with open(SESSIONID_FILE, "w") as f:
        f.write(sessionid)

    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)

    msg = await update.message.reply_text("🔐 Starting session login...")

    async def notify(text):
        await msg.edit_text(text)

    await create_session(sessionid, notify)


# 🚀 SEND FLOW
async def send_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Send message (old message will be replaced)")
    return ASK_MESSAGE


async def get_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(MESSAGE_FILE):
        os.remove(MESSAGE_FILE)

    with open(MESSAGE_FILE, "w", encoding="utf-8") as f:
        f.write(update.message.text.strip())

    await update.message.reply_text("✅ Message saved\n\nSend GC links (comma separated)")
    return ASK_GC


async def get_gc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sender_process, live_task, total_sent

    if not os.path.exists(SESSION_FILE):
        await update.message.reply_text("❌ Session not ready. Use /session first")
        return ConversationHandler.END

    total_sent = 0
    links = update.message.text.strip()

    cmd = [
        "python", "sender.py",
        "--thread-url", links,
        "--storage-state", SESSION_FILE,
        "--names", MESSAGE_FILE,
        "--headless", "false"
    ]

    sender_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid
    )

    status = await update.message.reply_text("🚀 Sending started…")
    live_task = asyncio.create_task(live_counter(status))

    return ConversationHandler.END


# 📊 LIVE COUNTER
async def live_counter(msg):
    global total_sent
    try:
        while sender_process and sender_process.poll() is None:
            await asyncio.sleep(4)
            total_sent += 15
            await msg.edit_text(
                f"📊 Live Status\n\n"
                f"✅ Sent: {total_sent}\n"
                f"🟢 Running\n\n"
                f"/stop to halt"
            )
    except:
        pass


# 🛑 STOP
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global sender_process, live_task

    if sender_process and sender_process.poll() is None:
        os.killpg(os.getpgid(sender_process.pid), signal.SIGTERM)
        sender_process = None
        if live_task:
            live_task.cancel()
        await update.message.reply_text("🛑 Sending stopped")
    else:
        await update.message.reply_text("ℹ️ No active sender")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("send", send_start)],
        states={
            ASK_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_message)],
            ASK_GC: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gc)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("session", set_session))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(conv)

    app.run_polling()


if __name__ == "__main__":
    main()
