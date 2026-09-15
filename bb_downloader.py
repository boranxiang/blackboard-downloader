#!/usr/bin/env python3
"""
Blackboard Learn PDF Downloader
Supports any school running Blackboard Learn.
Usage: python3 bb_downloader.py
"""

import re
import json
import argparse
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

CONTAINER_HANDLERS = {
    "resource/x-bb-folder",
    "resource/x-bb-lesson",
    "resource/x-bb-courselink",
    "resource/x-bb-blankpage",
}

# Nodes that should create a subfolder on disk when recursed into.
FOLDER_HANDLERS = {
    "resource/x-bb-folder",
    "resource/x-bb-lesson",
}

# ── Auth ──────────────────────────────────────────────────────────────────────

def wait_for_login(driver, base_url):
    driver.get(f"{base_url}/ultra/course")
    print("\nA browser window has opened.")
    print("Please log in to Blackboard, then come back here and press Enter.")
    input()


def get_session_from_browser(driver):
    session = requests.Session()
    for cookie in driver.get_cookies():
        session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"))
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })
    return session


# ── User & courses ────────────────────────────────────────────────────────────

def get_my_user_id(session, base_url):
    resp = session.get(f"{base_url}/learn/api/public/v1/users/me")
    if resp.status_code == 200:
        return resp.json().get("id")
    return None


def get_course_detail(session, base_url, course_id):
    resp = session.get(f"{base_url}/learn/api/public/v1/courses/{course_id}")
    if resp.status_code == 200:
        return resp.json()
    return None


def get_all_enrollments(session, base_url, user_id):
    """Fetch all course enrollments for the current user."""
    enrollments = []
    url = f"{base_url}/learn/api/public/v1/users/{user_id}/courses?limit=100"
    while url:
        resp = session.get(url)
        if resp.status_code != 200:
            print(f"  Failed to fetch enrollments: {resp.status_code}")
            break
        data = resp.json()
        enrollments.extend(data.get("results", []))
        next_page = data.get("paging", {}).get("nextPage")
        url = f"{base_url}{next_page}" if next_page else None
    return enrollments


def build_term_map(session, base_url, enrollments):
    """
    Returns a dict: { "Spring 2026 (26sprg)": [course, ...], ... }
    where each course = {"id": ..., "name": ..., "safe_name": ...}
    """
    print("  Fetching course details (this may take a moment)...")
    term_map = {}

    for enrollment in enrollments:
        raw_id = enrollment.get("courseId")
        if not raw_id:
            continue
        detail = get_course_detail(session, base_url, raw_id)
        if not detail:
            continue

        course_code = detail.get("courseId", "")   # e.g. "26sprgcasma225_c1"
        name = detail.get("name", "Unknown")
        term_label = detail.get("term", {}).get("name") or _infer_term(course_code) or "Unknown Term"
        safe_name = _safe(name)

        term_map.setdefault(term_label, []).append({
            "id": raw_id,
            "name": name,
            "safe_name": safe_name,
            "course_code": course_code,
        })

    return term_map


def _infer_term(course_code):
    """Try to guess a human-readable term from the courseId string."""
    m = re.match(r"(\d{2})(sprg|fall|sum[123]?)", course_code, re.IGNORECASE)
    if not m:
        return None
    yy, sem = m.group(1), m.group(2).lower()
    year = f"20{yy}"
    names = {"sprg": "Spring", "fall": "Fall", "sum": "Summer",
             "sum1": "Summer 1", "sum2": "Summer 2", "sum3": "Summer 3"}
    return f"{names.get(sem, sem.title())} {year}"


def _safe(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip()


def pick_term(term_map):
    """Interactive term picker. Returns list of selected courses."""
    terms = sorted(term_map.keys())
    print("\nAvailable terms:")
    for i, t in enumerate(terms, 1):
        print(f"  [{i}] {t}  ({len(term_map[t])} courses)")
    print("  [0] All terms")

    while True:
        raw = input("\nSelect term number: ").strip()
        if raw == "0":
            all_courses = [c for courses in term_map.values() for c in courses]
            return all_courses
        if raw.isdigit() and 1 <= int(raw) <= len(terms):
            return term_map[terms[int(raw) - 1]]
        print("  Invalid input, try again.")


def pick_courses(courses):
    """
    Interactive multi-select course picker.
    Accepts: 'all' / blank, comma-separated indices, hyphen ranges, or a mix
    (e.g. '1,3,5', '1-3', '1-3,5,7-9'). Returns the chosen subset in original order.
    """
    print("\nCourses in selected term:")
    for i, c in enumerate(courses, 1):
        print(f"  [{i}] {c['name']}")
    print("\nEnter course numbers to download (e.g. 1,3,5 or 1-3,5).")
    print("Press Enter or type 'all' for every course.")

    while True:
        raw = input("  > ").strip().lower()
        if raw == "" or raw == "all":
            return courses

        chosen = set()
        ok = True
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                parts = token.split("-")
                if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                    ok = False
                    break
                a, b = int(parts[0]), int(parts[1])
                if a > b:
                    a, b = b, a
                for n in range(a, b + 1):
                    if not 1 <= n <= len(courses):
                        ok = False
                        break
                    chosen.add(n)
                if not ok:
                    break
            else:
                if not token.isdigit():
                    ok = False
                    break
                n = int(token)
                if not 1 <= n <= len(courses):
                    ok = False
                    break
                chosen.add(n)

        if not ok or not chosen:
            print("  Invalid input, try again.")
            continue

        selected = [courses[i - 1] for i in sorted(chosen)]
        print("\nSelected courses:")
        for c in selected:
            print(f"  - {c['name']}")
        return selected


def filter_courses_by_query(courses, queries):
    """Filter courses by case-insensitive substring match against name or course code."""
    queries_lc = [q.lower() for q in queries]
    matched = []
    seen_match = {q: False for q in queries_lc}
    for c in courses:
        name_lc = c["name"].lower()
        code_lc = c.get("course_code", "").lower()
        for q in queries_lc:
            if q in name_lc or q in code_lc:
                matched.append(c)
                seen_match[q] = True
                break
    for q, hit in seen_match.items():
        if not hit:
            print(f"  Warning: no course matched '{q}'")
    return matched


# ── Content traversal ─────────────────────────────────────────────────────────

def get_top_level_sections(session, base_url, course_id):
    resp = session.get(f"{base_url}/learn/api/public/v1/courses/{course_id}/contents?limit=100")
    if resp.status_code != 200:
        return []
    sections = []
    for item in resp.json().get("results", []):
        sections.append({
            "id": item.get("id"),
            "name": _safe(item.get("title", "Untitled")),
        })
    return sections


def collect_files_recursive(session, base_url, course_id, item_id, extensions):
    """
    Recursively collect all downloadable files under item_id.
    Returns list of {"url": ..., "filename": ..., "rel_path": [folder, subfolder, ...]}
    where rel_path mirrors the Blackboard folder/lesson hierarchy below item_id.
    """
    files = []

    def fetch(node_id, rel_path):
        # Fetch node detail (contains body HTML)
        detail_resp = session.get(f"{base_url}/learn/api/public/v1/courses/{course_id}/contents/{node_id}")
        if detail_resp.status_code == 200:
            body = detail_resp.json().get("body", "")
            for f in _extract_from_body(body, base_url, extensions):
                f["rel_path"] = list(rel_path)
                files.append(f)

        # Fetch traditional attachments
        att_resp = session.get(f"{base_url}/learn/api/public/v1/courses/{course_id}/contents/{node_id}/attachments")
        if att_resp.status_code == 200:
            for att in att_resp.json().get("results", []):
                filename = att.get("fileName", "")
                mime = att.get("mimeType", "")
                if _matches(filename, mime, extensions):
                    dl_url = (
                        f"{base_url}/learn/api/public/v1/courses/{course_id}"
                        f"/contents/{node_id}/attachments/{att['id']}/download"
                    )
                    files.append({"url": dl_url, "filename": filename, "rel_path": list(rel_path)})

        # Recurse into children
        children_resp = session.get(
            f"{base_url}/learn/api/public/v1/courses/{course_id}/contents/{node_id}/children?limit=100"
        )
        if children_resp.status_code == 200:
            for child in children_resp.json().get("results", []):
                child_id = child.get("id")
                if not child_id:
                    continue
                handler = (child.get("contentHandler") or {}).get("id", "")
                if handler in FOLDER_HANDLERS:
                    child_name = _safe(child.get("title", "Untitled"))
                    fetch(child_id, rel_path + [child_name])
                else:
                    fetch(child_id, rel_path)

    fetch(item_id, [])
    return files


def _extract_from_body(body, base_url, extensions):
    """Parse Blackboard body HTML for file links (data-bbfile and plain hrefs)."""
    if not body:
        return []
    files = []
    soup = BeautifulSoup(body, "html.parser")

    for a in soup.find_all("a"):
        bbfile = a.get("data-bbfile")
        if bbfile:
            try:
                info = json.loads(bbfile)
                filename = info.get("displayName") or info.get("linkName", "")
                mime = info.get("mimeType", "")
                url = info.get("resourceUrl") or a.get("href", "")
                if url and _matches(filename, mime, extensions):
                    files.append({"url": url, "filename": filename})
            except (json.JSONDecodeError, AttributeError):
                pass
            continue

        href = a.get("href", "")
        if not href:
            continue
        filename = unquote(urlparse(href).path.split("/")[-1])
        if _matches(filename, "", extensions):
            files.append({"url": urljoin(base_url, href), "filename": filename})

    return files


def _matches(filename, mime, extensions):
    """Check if a file matches the requested extensions."""
    ext = Path(filename).suffix.lower()
    if extensions is None:
        return bool(ext or mime)
    if ext in extensions:
        return True
    # fallback: check mime type for common types
    mime_map = {
        "application/pdf": ".pdf",
        "application/vnd.ms-powerpoint": ".ppt",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }
    return mime_map.get(mime, "") in extensions


# ── Download ──────────────────────────────────────────────────────────────────

def download_file(session, url, dest_path: Path):
    if dest_path.exists():
        print(f"    skip (exists): {dest_path.name}")
        return False

    resp = session.get(url, stream=True, allow_redirects=True)
    if resp.status_code != 200:
        print(f"    failed ({resp.status_code}): {dest_path.name}")
        return False

    # Try to get real filename from Content-Disposition
    cd = resp.headers.get("Content-Disposition", "")
    if cd and "filename=" in cd:
        m = re.search(r'filename[^;=\n]*=([\'"]?)([^\'";\n]+)\1', cd)
        if m:
            real_name = m.group(2).strip()
            if Path(real_name).suffix:
                dest_path = dest_path.parent / _safe(real_name)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"    downloaded: {dest_path.name}")
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Download files from any Blackboard Learn instance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 bb_downloader.py
  python3 bb_downloader.py --url learn.bu.edu --output ~/Desktop/BB --ext .pdf .pptx
  python3 bb_downloader.py --courses CSU33012 "Machine Learning"
        """
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Blackboard domain, e.g. learn.bu.edu (prompted if not provided)"
    )
    parser.add_argument(
        "--output", "-o",
        default=str(Path.home() / "Downloads" / "Blackboard"),
        help="Download destination folder (default: ~/Downloads/Blackboard)"
    )
    parser.add_argument(
        "--ext",
        nargs="+",
        default=None,
        help="File extensions to download, e.g. --ext .pdf .pptx .docx (default: all)"
    )
    parser.add_argument(
        "--courses",
        nargs="+",
        default=None,
        help="Course names or IDs to download (substring match, case-insensitive). "
             "Skips the interactive course picker. Example: --courses CSU33012 'Machine Learning'"
    )
    return parser.parse_args()


def prompt_url():
    print("Enter your Blackboard domain (e.g. learn.bu.edu):")
    raw = input("  > ").strip().rstrip("/")
    if not raw.startswith("http"):
        raw = f"https://{raw}"
    return raw


def main():
    args = parse_args()

    base_url = args.url
    if base_url:
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")
    else:
        base_url = prompt_url()

    extensions = set(args.ext) if args.ext else None
    file_types = ", ".join(sorted(extensions)) if extensions else "all"
    print(f"\nFile types: {file_types}")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output folder: {output_dir}")

    # Launch browser for login
    options = Options()
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        wait_for_login(driver, base_url)
        session = get_session_from_browser(driver)
        driver.quit()

        print("\nFetching user info...")
        user_id = get_my_user_id(session, base_url)
        if not user_id:
            print("Could not retrieve user ID. Login may have failed.")
            return

        print("Fetching enrollments...")
        enrollments = get_all_enrollments(session, base_url, user_id)
        if not enrollments:
            print("No enrollments found.")
            return

        term_map = build_term_map(session, base_url, enrollments)
        if not term_map:
            print("No courses found.")
            return

        courses = pick_term(term_map)
        if args.courses:
            courses = filter_courses_by_query(courses, args.courses)
            if not courses:
                print("No courses matched --courses filter.")
                return
        else:
            courses = pick_courses(courses)

        print(f"\nStarting download for {len(courses)} course(s)...\n")
        total = 0

        for course in courses:
            print(f"[{course['name']}]")
            course_dir = output_dir / course["safe_name"]

            sections = get_top_level_sections(session, base_url, course["id"])
            if not sections:
                print("  No accessible content.")
                continue

            for section in sections:
                print(f"  /{section['name']}")
                section_dir = course_dir / section["name"]
                files = collect_files_recursive(session, base_url, course["id"], section["id"], extensions)
                for f in files:
                    subdirs = [_safe(p) for p in f.get("rel_path", []) if p]
                    dest = section_dir.joinpath(*subdirs, _safe(f["filename"]))
                    if download_file(session, f["url"], dest):
                        total += 1

        print(f"\nDone! Downloaded {total} file(s) to {output_dir}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
