#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import getpass
import os
import re
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService


OUT_FIELDS = ["name", "grade", "location", "date", "comment", "video"]

STYLE_MAP = {
    "os": "Onsight",
    "rp": "Redpoint",
    "flash": "Flash",
    "fl": "Flash",
    "tr": "Toprope",
    "pp": "Pinkpoint",
}

Locator = tuple[str, str]


# ---------- CSV / normalization helpers ----------

def clean(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.lower() == "null" else value


def squash(text: str | None) -> str:
    return re.sub(r"\s+", " ", clean(text)).strip()


def build_location(location_name: str | None, sector_name: str | None) -> str:
    parts: list[str] = []
    for part in (squash(location_name), squash(sector_name)):
        if part and part not in parts:
            parts.append(part)
    return " - ".join(parts)


def build_month_year(iso_date: str | None) -> str:
    raw = clean(iso_date)
    if not raw:
        return ""
    try:
        dt = datetime.strptime(raw[:10], "%Y-%m-%d")
        return dt.strftime("%Y-%m")
    except ValueError:
        return raw


def parse_multi_pitch(comment: str | None) -> tuple[bool, str]:
    text = clean(comment)
    if not text:
        return False, ""

    pattern = re.compile(r"^\s*multi-pitch\b\s*[:\-–—]?\s*", re.IGNORECASE)
    is_multi = bool(pattern.match(text))
    return is_multi, pattern.sub("", text, count=1).strip()


def prettify_style(style: str | None) -> str:
    key = clean(style).lower()
    return STYLE_MAP.get(key, key) if key else ""


def build_comment(style: str | None, raw_comment: str | None) -> tuple[bool, str]:
    is_multi, comment = parse_multi_pitch(raw_comment)
    style_text = prettify_style(style)

    if style_text and comment:
        return is_multi, f"{style_text} - {comment}"
    if style_text:
        return is_multi, style_text
    return is_multi, comment


def to_roman(n: int) -> str:
    vals = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    out = []
    for value, symbol in vals:
        while n >= value:
            out.append(symbol)
            n -= value
    return "".join(out)


def normalize_route_grade(grade: str | None) -> str:
    g = squash(grade)
    if not g:
        return ""

    # French scale stays as-is if it contains a/b/c anywhere.
    if re.search(r"[abc]", g, flags=re.IGNORECASE):
        return g

    # Convert UIAA like 6-, 6, 6+, 7- -> VI-, VI, VI+, VII-
    m = re.fullmatch(r"(\d+)\s*([+-]?)", g)
    if not m:
        return g

    number = int(m.group(1))
    suffix = m.group(2)
    return f"{to_roman(number)}{suffix}"


def target_file(route_boulder: str | None, is_multi: bool) -> str | None:
    kind = clean(route_boulder).upper()
    if kind == "BOULDER":
        return "boulder.csv"
    if kind == "ROUTE":
        return "multi.csv" if is_multi else "lead.csv"
    return None


def row_key(row: dict) -> tuple[str, str]:
    return squash(row.get("name", "")), squash(row.get("location", ""))


def ensure_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=OUT_FIELDS).writeheader()


def read_csv_rows(path: Path) -> list[dict]:
    ensure_csv(path)
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({field: clean(row.get(field, "")) for field in OUT_FIELDS})
    return rows


def append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    ensure_csv(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writerows(rows)


def convert_row(vl_row: dict) -> tuple[str | None, dict | None]:
    name = squash(vl_row.get("name"))
    location = build_location(vl_row.get("location_name"), vl_row.get("sector_name"))
    date = build_month_year(vl_row.get("date"))
    is_multi, comment = build_comment(vl_row.get("type"), vl_row.get("comment"))
    target = target_file(vl_row.get("route_boulder"), is_multi)

    if not target or not name or not location:
        return None, None

    grade = squash(vl_row.get("difficulty"))
    if target in {"lead.csv", "multi.csv"}:
        grade = normalize_route_grade(grade)

    return target, {
        "name": name,
        "grade": grade,
        "location": location,
        "date": date,
        "comment": comment,
        "video": "",
    }


def sync_vertical_life(input_csv: Path, user_dir: Path, dry_run: bool = False) -> None:
    targets = {
        "boulder.csv": user_dir / "boulder.csv",
        "lead.csv": user_dir / "lead.csv",
        "multi.csv": user_dir / "multi.csv",
    }

    existing = {
        name: {row_key(row) for row in read_csv_rows(path) if row["name"] and row["location"]}
        for name, path in targets.items()
    }
    new_rows = {name: [] for name in targets}
    seen_this_run = {name: set() for name in targets}

    with input_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for vl_row in reader:
            target, out_row = convert_row(vl_row)
            if not target or not out_row:
                continue

            key = row_key(out_row)
            if key in existing[target] or key in seen_this_run[target]:
                continue

            new_rows[target].append(out_row)
            seen_this_run[target].add(key)

    for name, rows in new_rows.items():
        print(f"{name}: {len(rows)} new row(s)")
        for row in rows:
            print(f"  + {row['name']} @ {row['location']}")
        if not dry_run:
            append_rows(targets[name], rows)


# ---------- Selenium helpers ----------

USERNAME_LOCATORS: list[Locator] = [
    (By.XPATH, "//label[contains(., 'Username or email')]/following::input[1]"),
    (By.CSS_SELECTOR, "input[type='email']"),
    (By.CSS_SELECTOR, "input[name*='user' i]"),
    (By.CSS_SELECTOR, "input[name*='email' i]"),
    (By.CSS_SELECTOR, "input[type='text']"),
]

PASSWORD_LOCATORS: list[Locator] = [
    (By.XPATH, "//label[contains(., 'Password')]/following::input[1]"),
    (By.CSS_SELECTOR, "input[type='password']"),
]

LOGIN_BUTTON_LOCATORS: list[Locator] = [
    (By.XPATH, "//button[normalize-space()='Sign In']"),
    (By.XPATH, "//button[normalize-space()='Login']"),
    (By.CSS_SELECTOR, "button[type='submit']"),
    (By.XPATH, "//*[@type='submit']"),
]

INFO_TAB_LOCATORS: list[Locator] = [
    (By.XPATH, "//*[self::a or self::button or self::div][normalize-space()='Info']"),
]

ABOUT_EDIT_LOCATORS: list[Locator] = [
    (
        By.XPATH,
        "//div[contains(@class,'separator-container')][.//div[normalize-space()='About']]"
        "//div[contains(@class,'icon-container') and contains(@class,'pointer')]",
    ),
    (
        By.XPATH,
        "//div[normalize-space()='About']/following-sibling::div"
        "[contains(@class,'icon-container') and contains(@class,'pointer')][1]",
    ),
    (
        By.XPATH,
        "//*[contains(@class,'user-separator')][.//div[normalize-space()='About']]"
        "//*[contains(@class,'icon-container') and contains(@class,'pointer')]",
    ),
]

EXPORT_BUTTON_LOCATORS: list[Locator] = [
    (
        By.XPATH,
        "//button[.//div[contains(@class,'button-text') and normalize-space()='Download']]",
    ),
    (
        By.XPATH,
        "//button[contains(@class,'button-container')][.//div[normalize-space()='Download']]",
    ),
    (
        By.XPATH,
        "//*[self::button or self::a][normalize-space()='Download']",
    ),
    (
        By.XPATH,
        "//*[self::button or self::a or self::div][contains(normalize-space(),'Download')]",
    ),
]


def get_password(cli_password: str | None) -> str:
    if cli_password:
        return cli_password
    if env_password := os.environ.get("VL_PASSWORD"):
        return env_password
    return getpass.getpass("Vertical-Life password: ")


def human_check_present(driver) -> bool:
    try:
        text = driver.page_source.lower()
    except Exception:
        return False
    return any(
        marker in text
        for marker in (
            "are you human",
            "verify you are human",
            "verifying you are human",
            "checking your browser",
            "cloudflare",
            "captcha",
            "i am human",
        )
    )


def scroll_page(driver) -> None:
    driver.execute_script(
        """
        window.scrollBy(0, 500);
        for (const el of document.querySelectorAll('div, section, main, aside')) {
            try {
                const s = getComputedStyle(el);
                const canScroll =
                    (s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                    el.scrollHeight > el.clientHeight + 20;
                if (canScroll) el.scrollTop += 500;
            } catch (_) {}
        }
        """
    )


def find_first(driver, locators: list[Locator], *, clickable: bool = False):
    for by, value in locators:
        try:
            for el in driver.find_elements(by, value):
                try:
                    if not el.is_displayed():
                        continue
                    if clickable and not el.is_enabled():
                        continue
                    return el
                except StaleElementReferenceException:
                    continue
        except WebDriverException:
            continue
    return None


def wait_for_element(
    driver,
    locators: list[Locator],
    timeout: int = 15,
    *,
    clickable: bool = False,
    scroll: bool = False,
):
    deadline = time.time() + timeout
    last_exc = None

    while time.time() < deadline:
        try:
            el = find_first(driver, locators, clickable=clickable)
            if el is not None:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                except Exception:
                    pass
                return el
        except Exception as exc:
            last_exc = exc

        if scroll:
            scroll_page(driver)
        time.sleep(0.25)

    raise RuntimeError(f"Timed out waiting for element. Locators: {locators}") from last_exc


def type_into(driver, locators: list[Locator], text: str, timeout: int = 15) -> None:
    el = wait_for_element(driver, locators, timeout=timeout)
    el.clear()
    el.send_keys(text)


def click_any(
    driver,
    locators: list[Locator],
    timeout: int = 15,
    retries: int = 5,
    *,
    scroll: bool = False,
) -> None:
    last_exc = None
    for _ in range(retries):
        try:
            el = wait_for_element(
                driver,
                locators,
                timeout=timeout,
                clickable=True,
                scroll=scroll,
            )
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', inline:'center'});", el
            )
            time.sleep(0.15)
            try:
                el.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", el)
            return
        except (RuntimeError, StaleElementReferenceException, WebDriverException) as exc:
            last_exc = exc
            time.sleep(0.4)

    raise RuntimeError(f"Could not click element. Locators: {locators}") from last_exc


def wait_for_login_complete(driver, timeout: int = 300, headed: bool = False) -> None:
    deadline = time.time() + timeout
    warned = False

    while time.time() < deadline:
        current_url = driver.current_url.lower()
        try:
            page_text = driver.page_source.lower()
        except Exception:
            page_text = ""

        if "my-profile" in current_url:
            return

        if (
            "8a.nu" in current_url
            and "login" not in current_url
            and "vertical-life.info" not in current_url
            and "password" not in page_text
        ):
            return

        if human_check_present(driver):
            if not headed:
                raise RuntimeError(
                    "Human verification detected. Re-run with --headed and complete it manually."
                )
            if not warned:
                print("Human verification detected. Please solve it in the browser window.")
                warned = True

        time.sleep(1)

    raise RuntimeError(f"Timed out waiting for login to complete. Current URL: {driver.current_url}")


def dismiss_cookie_banner(driver) -> None:
    try:
        click_any(
            driver,
            [
                (By.XPATH, "//button[contains(.,'Accept')]"),
                (By.XPATH, "//button[contains(.,'Allow all')]"),
                (By.XPATH, "//button[contains(.,'I agree')]"),
                (By.XPATH, "//button[contains(.,'Got it')]"),
            ],
            timeout=3,
            retries=1,
        )
    except Exception:
        pass


def wait_for_download(download_dir: Path, existing_files: set[str], timeout: int = 45) -> Path:
    deadline = time.time() + timeout
    while time.time() < deadline:
        new_files = [
            p for p in download_dir.iterdir()
            if p.is_file() and p.name not in existing_files and not p.name.endswith(".part")
        ]
        if new_files:
            return max(new_files, key=lambda p: p.stat().st_mtime)
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for CSV download to finish.")


# ---------- Fetch logic ----------

def fetch_vertical_life_csv(
    user_slug: str,
    vl_username: str,
    vl_password: str,
    user_dir: Path,
    headed: bool = False,
    timeout_sec: int = 20,
    login_timeout_sec: int = 300,
    geckodriver_path: str | None = None,
    firefox_binary: str | None = None,
) -> Path:
    user_dir.mkdir(parents=True, exist_ok=True)
    out_csv = user_dir / f"vl_{user_slug}.csv"
    debug_png = user_dir / f"vl_{user_slug}_debug.png"
    debug_html = user_dir / f"vl_{user_slug}_debug.html"

    options = FirefoxOptions()
    if not headed:
        options.add_argument("-headless")
    if firefox_binary:
        options.binary_location = firefox_binary

    options.set_preference("browser.download.folderList", 2)
    options.set_preference("browser.download.dir", str(user_dir.resolve()))
    options.set_preference("browser.download.useDownloadDir", True)
    options.set_preference("browser.download.manager.showWhenStarting", False)
    options.set_preference(
        "browser.helperApps.neverAsk.saveToDisk",
        ",".join(
            [
                "text/csv",
                "application/csv",
                "application/octet-stream",
                "application/vnd.ms-excel",
            ]
        ),
    )
    options.set_preference("pdfjs.disabled", True)

    service = FirefoxService(executable_path=geckodriver_path) if geckodriver_path else FirefoxService()
    driver = webdriver.Firefox(service=service, options=options)

    try:
        driver.set_window_size(1440, 1400)
        existing_files = {p.name for p in user_dir.iterdir() if p.is_file()}

        driver.get("https://www.8a.nu/login?redirect=%2F")
        dismiss_cookie_banner(driver)

        type_into(driver, USERNAME_LOCATORS, vl_username, timeout=timeout_sec)
        type_into(driver, PASSWORD_LOCATORS, vl_password, timeout=timeout_sec)
        click_any(driver, LOGIN_BUTTON_LOCATORS, timeout=timeout_sec, retries=3)

        wait_for_login_complete(driver, timeout=login_timeout_sec, headed=headed)

        driver.get("https://www.8a.nu/my-profile")
        time.sleep(2)

        try:
            click_any(driver, INFO_TAB_LOCATORS, timeout=5, retries=2)
            time.sleep(1)
        except Exception:
            pass

        click_any(driver, ABOUT_EDIT_LOCATORS, timeout=timeout_sec, retries=5, scroll=True)
        time.sleep(1.5)

        click_any(driver, EXPORT_BUTTON_LOCATORS, timeout=30, retries=5, scroll=True)
        downloaded = wait_for_download(user_dir, existing_files, timeout=45)

        if downloaded.resolve() != out_csv.resolve():
            if out_csv.exists():
                out_csv.unlink()
            downloaded.rename(out_csv)

        print(f"Downloaded raw CSV to {out_csv}")
        return out_csv

    except Exception:
        try:
            driver.save_screenshot(str(debug_png))
            debug_html.write_text(driver.page_source, encoding="utf-8")
            print(f"Saved debug screenshot to {debug_png}")
            print(f"Saved debug HTML to {debug_html}")
        except Exception:
            pass
        raise
    finally:
        driver.quit()


# ---------- CLI ----------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync Vertical-Life export into boulder.csv, lead.csv, multi.csv"
    )
    parser.add_argument("--user", required=True, help="Short user slug, e.g. paul")
    parser.add_argument("--base-dir", type=Path, default=Path(""), help="Base directory for user folders")
    parser.add_argument("--input-csv", type=Path, help="Optional path to an existing Vertical-Life CSV")
    parser.add_argument("--fetch", action="store_true", help="Fetch the CSV from Vertical-Life before syncing")
    parser.add_argument("--vl-username", help="Vertical-Life login name/email")
    parser.add_argument("--vl-password", help="Vertical-Life password (omit to prompt)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be added")
    parser.add_argument("--headed", action="store_true", help="Show browser window while fetching")
    parser.add_argument("--timeout-sec", type=int, default=20, help="Generic Selenium wait timeout")
    parser.add_argument(
        "--login-timeout-sec",
        type=int,
        default=300,
        help="How long to wait for manual human verification",
    )
    parser.add_argument("--geckodriver-path", help="Optional path to geckodriver")
    parser.add_argument("--firefox-binary", help="Optional path to firefox binary")
    args = parser.parse_args()

    user_dir = args.base_dir / args.user
    default_csv = user_dir / f"vl_{args.user}.csv"
    input_csv = args.input_csv or default_csv

    if args.fetch:
        if not args.vl_username:
            parser.error("--fetch requires --vl-username")
        input_csv = fetch_vertical_life_csv(
            user_slug=args.user,
            vl_username=args.vl_username,
            vl_password=get_password(args.vl_password),
            user_dir=user_dir,
            headed=args.headed,
            timeout_sec=args.timeout_sec,
            login_timeout_sec=args.login_timeout_sec,
            geckodriver_path=args.geckodriver_path,
            firefox_binary=args.firefox_binary,
        )
    elif not input_csv.exists():
        parser.error(f"Input CSV not found: {input_csv}. Use --fetch or provide --input-csv.")

    sync_vertical_life(input_csv=input_csv, user_dir=user_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
