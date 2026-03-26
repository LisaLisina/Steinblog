#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import getpass
import os
import re
import time
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


# ---------- CSV helpers ----------

def clean_value(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.lower() == "null" else value


def norm_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def build_location(location_name: str, sector_name: str) -> str:
    parts: list[str] = []
    for part in (clean_value(location_name), clean_value(sector_name)):
        part = norm_spaces(part)
        if part and part not in parts:
            parts.append(part)
    return " - ".join(parts)


def build_date(iso_date: str) -> str:
    iso_date = clean_value(iso_date)
    return iso_date.split("T", 1)[0] if iso_date else ""


def parse_multi_pitch(raw_comment: str) -> tuple[bool, str]:
    comment = clean_value(raw_comment)
    if not comment:
        return False, ""

    pattern = re.compile(r"^\s*multi-pitch\b\s*[:\-–—]?\s*", re.IGNORECASE)
    if pattern.match(comment):
        return True, pattern.sub("", comment, count=1).strip()

    return False, comment


def prettify_style(style: str) -> str:
    style = clean_value(style).lower()
    return STYLE_MAP.get(style, style) if style else ""


def build_comment(style: str, raw_comment: str) -> tuple[bool, str]:
    is_multi, cleaned_comment = parse_multi_pitch(raw_comment)
    style_text = prettify_style(style)

    if style_text and cleaned_comment:
        return is_multi, f"{style_text} - {cleaned_comment}"
    if style_text:
        return is_multi, style_text
    return is_multi, cleaned_comment


def target_file_for_row(route_boulder: str, is_multi: bool) -> str | None:
    kind = clean_value(route_boulder).upper()
    if kind == "BOULDER":
        return "boulder.csv"
    if kind == "ROUTE":
        return "multi.csv" if is_multi else "lead.csv"
    return None


def row_key(name: str, location: str) -> tuple[str, str]:
    return norm_spaces(name), norm_spaces(location)


def ensure_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
            writer.writeheader()


def normalize_existing_csv(path: Path) -> None:
    ensure_csv(path)

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if fields == OUT_FIELDS:
            return
        rows = [{field: clean_value(row.get(field, "")) for field in OUT_FIELDS} for row in reader]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def load_existing_rows(path: Path) -> list[dict]:
    normalize_existing_csv(path)
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [{field: clean_value(row.get(field, "")) for field in OUT_FIELDS} for row in reader]


def load_existing_keys(path: Path) -> set[tuple[str, str]]:
    return {
        row_key(r["name"], r["location"])
        for r in load_existing_rows(path)
        if r["name"] and r["location"]
    }


def append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    normalize_existing_csv(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        writer.writerows(rows)


def convert_row(vl_row: dict) -> tuple[str | None, dict | None]:
    name = norm_spaces(clean_value(vl_row.get("name", "")))
    location = build_location(vl_row.get("location_name", ""), vl_row.get("sector_name", ""))
    date = build_date(vl_row.get("date", ""))
    grade = clean_value(vl_row.get("difficulty", ""))
    is_multi, comment = build_comment(vl_row.get("type", ""), vl_row.get("comment", ""))

    target = target_file_for_row(vl_row.get("route_boulder", ""), is_multi)
    if not target or not name or not location:
        return None, None

    out_row = {
        "name": name,
        "grade": grade,
        "location": location,
        "date": date,
        "comment": comment,
        "video": "",
    }
    return target, out_row


def sync_vertical_life(input_csv: Path, out_dir: Path, dry_run: bool = False) -> None:
    targets = {
        "boulder.csv": out_dir / "boulder.csv",
        "lead.csv": out_dir / "lead.csv",
        "multi.csv": out_dir / "multi.csv",
    }

    existing_keys = {name: load_existing_keys(path) for name, path in targets.items()}
    new_rows = {name: [] for name in targets}
    seen_this_run = {name: set() for name in targets}

    with input_csv.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for vl_row in reader:
            target_name, out_row = convert_row(vl_row)
            if not target_name or not out_row:
                continue

            key = row_key(out_row["name"], out_row["location"])
            if key in existing_keys[target_name] or key in seen_this_run[target_name]:
                continue

            new_rows[target_name].append(out_row)
            seen_this_run[target_name].add(key)

    for target_name, rows in new_rows.items():
        print(f"{target_name}: {len(rows)} new row(s)")
        for row in rows:
            print(f"  + {row['name']} @ {row['location']}")
        if not dry_run:
            append_rows(targets[target_name], rows)


# ---------- Selenium helpers ----------

USERNAME_LOCATORS: list[Locator] = [
    (By.XPATH, "//label[contains(., 'Username or email')]/following::input[1]"),
    (By.CSS_SELECTOR, "input[type='email']"),
    (By.CSS_SELECTOR, "input[type='text']"),
    (By.CSS_SELECTOR, "input[name*='user' i]"),
    (By.CSS_SELECTOR, "input[name*='email' i]"),
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
    (By.XPATH, "//*[contains(@class,'tab') and normalize-space()='Info']"),
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

def _get_password(cli_password: str | None) -> str:
    if cli_password:
        return cli_password
    env_password = os.environ.get("VL_PASSWORD")
    if env_password:
        return env_password
    return getpass.getpass("Vertical-Life password: ")


def _page_text(driver) -> str:
    try:
        return driver.page_source.lower()
    except Exception:
        return ""


def _human_check_present(driver) -> bool:
    text = _page_text(driver)
    markers = [
        "are you human",
        "verify you are human",
        "verifying you are human",
        "checking your browser",
        "cloudflare",
        "captcha",
        "i am human",
    ]
    return any(marker in text for marker in markers)


def _find_first_now(driver, locators: list[Locator], *, visible: bool = True, clickable: bool = False):
    for by, value in locators:
        try:
            for el in driver.find_elements(by, value):
                try:
                    if visible and not el.is_displayed():
                        continue
                    if clickable and (not el.is_displayed() or not el.is_enabled()):
                        continue
                    return el
                except StaleElementReferenceException:
                    continue
        except WebDriverException:
            continue
    return None


def _wait_for_first(driver, locators: list[Locator], timeout: int = 15, *, visible: bool = True, clickable: bool = False):
    deadline = time.time() + timeout
    last_exc = None

    while time.time() < deadline:
        try:
            el = _find_first_now(driver, locators, visible=visible, clickable=clickable)
            if el is not None:
                return el
        except Exception as exc:
            last_exc = exc
        time.sleep(0.2)

    raise RuntimeError(f"Timed out waiting for element. Locators: {locators}") from last_exc


def _type_into(driver, locators: list[Locator], text: str, timeout: int = 15) -> None:
    el = _wait_for_first(driver, locators, timeout=timeout, visible=True)
    el.clear()
    el.send_keys(text)


def _click_any(driver, locators: list[Locator], timeout: int = 15, retries: int = 5) -> None:
    last_exc = None

    for _ in range(retries):
        try:
            el = _wait_for_first(driver, locators, timeout=timeout, visible=True, clickable=True)
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                el,
            )
            time.sleep(0.15)

            try:
                el.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", el)
            return

        except (StaleElementReferenceException, RuntimeError, WebDriverException) as exc:
            last_exc = exc
            time.sleep(0.4)

    raise RuntimeError(f"Could not click element. Locators: {locators}") from last_exc


def _wait_for_login_complete(driver, timeout: int = 300, headed: bool = False) -> None:
    deadline = time.time() + timeout
    warned = False

    while time.time() < deadline:
        current_url = driver.current_url.lower()
        text = _page_text(driver)

        if "my-profile" in current_url:
            return

        if (
            "8a.nu" in current_url
            and "login" not in current_url
            and "vertical-life.info" not in current_url
            and "password" not in text
        ):
            return

        if _human_check_present(driver):
            if not headed:
                raise RuntimeError(
                    "Human verification detected. Re-run with --headed and complete it manually."
                )
            if not warned:
                print("Human verification detected. Please solve it in the browser window.")
                warned = True

        time.sleep(1)

    raise RuntimeError(f"Timed out waiting for login to complete. Current URL: {driver.current_url}")


def _dismiss_cookie_banner(driver) -> None:
    cookie_locators = [
        (By.XPATH, "//button[contains(.,'Accept')]"),
        (By.XPATH, "//button[contains(.,'Allow all')]"),
        (By.XPATH, "//button[contains(.,'I agree')]"),
        (By.XPATH, "//button[contains(.,'Got it')]"),
    ]
    try:
        _click_any(driver, cookie_locators, timeout=3, retries=1)
    except Exception:
        pass


def _scroll_page_and_containers(driver) -> None:
    driver.execute_script(
        """
        window.scrollBy(0, Math.max(450, Math.floor(window.innerHeight * 0.8)));

        const nodes = Array.from(document.querySelectorAll('div, section, main, aside'));
        for (const el of nodes) {
            try {
                const style = getComputedStyle(el);
                const overflowY = style.overflowY;
                const canScroll = (overflowY === 'auto' || overflowY === 'scroll') &&
                                  el.scrollHeight > el.clientHeight + 40;
                if (canScroll) {
                    el.scrollTop = Math.min(
                        el.scrollTop + Math.max(300, Math.floor(el.clientHeight * 0.8)),
                        el.scrollHeight
                    );
                }
            } catch (e) {}
        }
        """
    )


def _scroll_until_found(
    driver,
    locators: list[Locator],
    timeout: int = 20,
    *,
    visible: bool = True,
    clickable: bool = False,
):
    deadline = time.time() + timeout

    while time.time() < deadline:
        el = _find_first_now(driver, locators, visible=visible, clickable=clickable)
        if el is not None:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                time.sleep(0.2)
            except Exception:
                pass
            return el

        driver.execute_script(
            """
            window.scrollBy(0, 500);

            const nodes = Array.from(document.querySelectorAll('div, section, main, aside'));
            for (const el of nodes) {
                try {
                    const style = getComputedStyle(el);
                    const canScroll =
                        (style.overflowY === 'auto' || style.overflowY === 'scroll') &&
                        el.scrollHeight > el.clientHeight + 20;

                    if (canScroll) {
                        el.scrollTop += 500;
                    }
                } catch (e) {}
            }
            """
        )
        time.sleep(0.4)

    raise RuntimeError(f"Timed out while scrolling for element. Locators: {locators}")

def _wait_for_download(download_dir: Path, existing_files: set[str], timeout: int = 30) -> Path:
    deadline = time.time() + timeout
    while time.time() < deadline:
        files = [p for p in download_dir.iterdir() if p.is_file()]
        new_files = [p for p in files if p.name not in existing_files]
        finished = [p for p in new_files if not p.name.endswith(".part")]
        if finished:
            return max(finished, key=lambda p: p.stat().st_mtime)
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for CSV download to finish.")


def _dump_debug_candidates(driver) -> None:
    try:
        candidates = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'separator-container')][.//div[normalize-space()='About']]"
            "//div[contains(@class,'icon-container')]",
        )
        print(f"Found {len(candidates)} About icon candidate(s).")
        for idx, el in enumerate(candidates[:5]):
            try:
                print(f"\n--- About candidate {idx} ---")
                print(el.get_attribute("outerHTML")[:1500])
            except Exception:
                pass
    except Exception:
        pass


# ---------- Fetch logic ----------

def fetch_vertical_life_csv(
    user_slug: str,
    vl_username: str,
    vl_password: str,
    raw_dir: Path,
    headed: bool = False,
    timeout_sec: int = 20,
    login_timeout_sec: int = 300,
    geckodriver_path: str | None = None,
    firefox_binary: str | None = None,
) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_csv = raw_dir / f"vl_{user_slug}.csv"
    debug_png = raw_dir / f"vl_{user_slug}_debug.png"
    debug_html = raw_dir / f"vl_{user_slug}_debug.html"

    options = FirefoxOptions()
    if not headed:
        options.add_argument("-headless")
    if firefox_binary:
        options.binary_location = firefox_binary

    options.set_preference("browser.download.folderList", 2)
    options.set_preference("browser.download.dir", str(raw_dir.resolve()))
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
        existing_files = {p.name for p in raw_dir.iterdir() if p.is_file()}

        # Login
        driver.get("https://www.8a.nu/login?redirect=%2F")
        _dismiss_cookie_banner(driver)

        _type_into(driver, USERNAME_LOCATORS, vl_username, timeout=timeout_sec)
        _type_into(driver, PASSWORD_LOCATORS, vl_password, timeout=timeout_sec)
        _click_any(driver, LOGIN_BUTTON_LOCATORS, timeout=timeout_sec, retries=3)

        _wait_for_login_complete(driver, timeout=login_timeout_sec, headed=headed)

        # Profile
        driver.get("https://www.8a.nu/my-profile")
        time.sleep(2)

        # Info tab if needed
        try:
            _click_any(driver, INFO_TAB_LOCATORS, timeout=5, retries=2)
            time.sleep(1)
        except Exception:
            pass

        # Click exact About edit icon from your HTML
        _dump_debug_candidates(driver)
        _click_any(driver, ABOUT_EDIT_LOCATORS, timeout=timeout_sec, retries=5)
        time.sleep(1.5)

        # Go straight for the real Download button in the opened panel/modal
        _scroll_until_found(driver, EXPORT_BUTTON_LOCATORS, timeout=30, visible=True, clickable=True)
        _click_any(driver, EXPORT_BUTTON_LOCATORS, timeout=timeout_sec, retries=5)
        downloaded = _wait_for_download(raw_dir, existing_files, timeout=45)

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
    parser.add_argument("out_dir", type=Path, help="Output directory containing target CSVs")
    parser.add_argument("--input-csv", type=Path, help="Path to an already-downloaded Vertical-Life CSV")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be added")
    parser.add_argument("--fetch", action="store_true", help="Fetch the CSV from Vertical-Life before syncing")
    parser.add_argument("--user", help="Short user slug, e.g. paul -> data/raw/vl_paul.csv")
    parser.add_argument("--vl-username", help="Vertical-Life login name/email")
    parser.add_argument("--vl-password", help="Vertical-Life password (omit to prompt)")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"), help="Directory for downloaded raw CSVs")
    parser.add_argument("--headed", action="store_true", help="Show browser window while fetching")
    parser.add_argument("--timeout-sec", type=int, default=20, help="Generic Selenium wait timeout")
    parser.add_argument("--login-timeout-sec", type=int, default=300, help="How long to wait for manual human verification")
    parser.add_argument("--geckodriver-path", help="Optional path to geckodriver")
    parser.add_argument("--firefox-binary", help="Optional path to firefox binary")

    args = parser.parse_args()
    input_csv = args.input_csv

    if args.fetch:
        if not args.user:
            parser.error("--fetch requires --user")
        if not args.vl_username:
            parser.error("--fetch requires --vl-username")

        password = _get_password(args.vl_password)
        input_csv = fetch_vertical_life_csv(
            user_slug=args.user,
            vl_username=args.vl_username,
            vl_password=password,
            raw_dir=args.raw_dir,
            headed=args.headed,
            timeout_sec=args.timeout_sec,
            login_timeout_sec=args.login_timeout_sec,
            geckodriver_path=args.geckodriver_path,
            firefox_binary=args.firefox_binary,
        )

    if input_csv is None:
        parser.error("Provide either --input-csv or --fetch")

    sync_vertical_life(input_csv=input_csv, out_dir=args.out_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
