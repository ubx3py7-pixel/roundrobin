import argparse
import os
import re
import asyncio
import random
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ================= CONFIG =================
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1280, "height": 800}

LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-extensions",
]

DM_SELECTOR = 'div[role="textbox"]'
# =========================================


def sanitize_input(raw):
    if isinstance(raw, list):
        return " ".join(raw)
    return raw


def parse_messages(names_arg):
    if isinstance(names_arg, list):
        names_arg = " ".join(names_arg)

    if isinstance(names_arg, str) and names_arg.endswith(".txt") and os.path.exists(names_arg):
        with open(names_arg, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]

    content = str(names_arg).replace("＆", "&")
    parts = re.split(r"\s*&\s*", content)
    return [p.strip() for p in parts if p.strip()]


def same_thread(current, target):
    try:
        return current.split("/direct/t/")[1].split("/")[0] == \
               target.split("/direct/t/")[1].split("/")[0]
    except Exception:
        return False


# 🔔 AUTO CLICK "NOT NOW" (TURN ON NOTIFICATIONS)
async def handle_notifications_popup(page):
    try:
        buttons = page.locator("button")
        count = await buttons.count()
        for i in range(count):
            txt = (await buttons.nth(i).inner_text()).lower()
            if "not now" in txt:
                await buttons.nth(i).click()
                await asyncio.sleep(0.3)
                break
    except Exception:
        pass


async def wait_login_settled(page):
    try:
        await page.wait_for_selector("body", timeout=30000)
    except:
        pass
    await asyncio.sleep(1)
    await handle_notifications_popup(page)


async def login_if_needed(args, storage_path, headless):
    if os.path.exists(storage_path):
        print("Using existing storage state, skipping login.")
        return True

    if not args.username or not args.password:
        print("Error: Username and password required for initial login.")
        return False

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=LAUNCH_ARGS)
        context = await browser.new_context(
            user_agent=DESKTOP_UA,
            viewport=VIEWPORT
        )
        page = await context.new_page()

        try:
            print("Logging in to Instagram...")
            await page.goto("https://www.instagram.com/", timeout=60000)
            await page.wait_for_selector('input[name="username"]', timeout=30000)
            await page.fill('input[name="username"]', args.username)
            await page.fill('input[name="password"]', args.password)
            await page.click('button[type="submit"]')

            await wait_login_settled(page)

            await page.goto("https://www.instagram.com/direct/inbox/", timeout=60000)
            await wait_login_settled(page)

            print("Login settled, saving storage state.")
            await context.storage_state(path=storage_path)
            return True

        except Exception as e:
            print(f"Login error: {e}")
            return False

        finally:
            await browser.close()


async def process_tab(tab_id, page, target_url, msg):
    try:
        if not same_thread(page.url, target_url):
            await page.goto(target_url, timeout=60000)

        await handle_notifications_popup(page)
        await page.wait_for_selector(DM_SELECTOR, timeout=30000)

        await asyncio.sleep(random.uniform(0.3, 0.5))
        await page.click(DM_SELECTOR)
        await page.fill(DM_SELECTOR, msg)
        await page.keyboard.press("Enter")

        print(f"[TAB {tab_id}] Sent: {msg[:50]}")
        await asyncio.sleep(random.uniform(0.3, 0.5))
        return True

    except Exception as e:
        print(f"[TAB {tab_id}] Failed: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(
        description="Instagram DM Infinite Sender (AUTO LOGIN, FAST, 15 GCs)"
    )
    parser.add_argument("--username", required=False)
    parser.add_argument("--password", required=False)
    parser.add_argument("--thread-url", required=True)
    parser.add_argument("--names", nargs="+", default=["m.txt"])
    parser.add_argument("--headless", default="true", choices=["true", "false"])
    parser.add_argument("--storage-state", required=True)

    args = parser.parse_args()
    args.names = sanitize_input(args.names)
    headless = args.headless == "true"

    ok = await login_if_needed(args, args.storage_state, headless)
    if not ok:
        print("Login failed, exiting.")
        return

    thread_urls = [u.strip() for u in args.thread_url.split(",") if u.strip()]
    messages = parse_messages(args.names)

    print(f"Loaded {len(messages)} messages. Fast sending started.")

    batch_size = 15
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, args=LAUNCH_ARGS)
        context = await browser.new_context(
            storage_state=args.storage_state,
            user_agent=DESKTOP_UA,
            viewport=VIEWPORT
        )

        pages = [await context.new_page() for _ in range(batch_size)]
        total = 0
        batch = 0
        msg_idx = 0

        try:
            while True:
                print(f"\n--- Batch {batch + 1} ---")
                tasks = []
                for i in range(batch_size):
                    url = thread_urls[(batch * batch_size + i) % len(thread_urls)]
                    msg = messages[msg_idx % len(messages)]
                    tasks.append(asyncio.create_task(
                        process_tab(i + 1, pages[i], url, msg)
                    ))
                    msg_idx += 1

                results = await asyncio.gather(*tasks)
                success = sum(1 for r in results if r)
                total += success
                batch += 1

                print(f"Batch {batch} completed: {success}/{batch_size}")
                print(f"Total messages sent: {total}")

                await asyncio.sleep(random.uniform(0.4, 0.6))

        except KeyboardInterrupt:
            print("Stopped by user.")

        finally:
            for p in pages:
                try:
                    await p.close()
                except:
                    pass
            await context.close()
            await browser.close()
            print(f"Finished. Total sent: {total}")


if __name__ == "__main__":
    asyncio.run(main())