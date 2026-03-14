import os, smtplib, datetime, time, json, gzip, re, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import urllib.request, urllib.parse
import anthropic

TODAY    = datetime.date.today().strftime("%d %B %Y")
TODAY_ISO = datetime.date.today().strftime("%Y-%m-%d")
WEEK_AGO = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%d %B %Y")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ---- Step 1: Fetch real pages (GitHub Actions HAS internet access) ----------

# All sources are fetched via RSS -- either native feeds or Google News RSS proxies.
# Google News RSS acts as a reliable proxy for sites that block direct HTTP access.

# Direct page fetch (these sites permit bot access)
SOURCES = [
    ("FIE Letters 2026",   "https://fie.org/fie/documents/letters/2026"),
    ("FIE News",           "https://fie.org/articles"),
    ("Sport&Politics",     "https://www.sportandpolitics.de"),
    ("Francsjeux EN",      "https://www.francsjeux.com/en"),
    ("The Inquisitor",     "https://www.the-inquisitor-magazine.com"),
    ("FFE French Fencing", "https://www.ffescrime.fr/"),
]

# SSL bypass needed for this host
SSL_BYPASS_SOURCES = [
    ("EFC Portal News",    "https://www.eurofencing.info/news"),
]

RSS_SOURCES = [
    # EFC Portal RSS (direct -- avoids SSL bypass for RSS)
    ("EFC Portal RSS",
     "https://www.eurofencing.info/rss"),
    # FIE official RSS
    ("FIE News RSS",
     "https://fie.org/rss"),
    # British Fencing -- Google News proxy (direct feed blocks bots)
    ("British Fencing via Google News",
     "https://news.google.com/rss/search?q=site:britishfencing.com&hl=en&gl=US&ceid=US:en"),
    # InsideTheGames -- Google News proxy (direct RSS empty/blocked)
    ("InsideTheGames Fencing via Google News",
     "https://news.google.com/rss/search?q=site:insidethegames.biz+fencing&hl=en&gl=US&ceid=US:en"),
    ("InsideTheGames FIE via Google News",
     "https://news.google.com/rss/search?q=site:insidethegames.biz+FIE&hl=en&gl=US&ceid=US:en"),
    # FFE via Google News proxy
    ("FFE French Fencing via Google News",
     "https://news.google.com/rss/search?q=site:ffescrime.fr&hl=en&gl=FR&ceid=FR:fr"),
    # Broad EFC/FIE fencing news
    ("Google News EFC FIE",
     "https://news.google.com/rss/search?q=EFC+FIE+fencing+European&hl=en&gl=US&ceid=US:en"),
    ("Google News Fencing 2026",
     "https://news.google.com/rss/search?q=fencing+championship+2026&hl=en&gl=US&ceid=US:en"),
]

# SOCMINT sources -- fetched separately with dedicated function
SOCMINT_RSS = [
    # EFC Twitter @eurofencing -- Google News indexes tweets via press pickup
    ("SOCMINT: EFC Twitter @eurofencing",
     "https://news.google.com/rss/search?q=eurofencing+Twitter&hl=en&gl=US&ceid=US:en"),
    # FIE Twitter @FIEfencing -- Google News proxy (direct Twitter blocked)
    ("SOCMINT: FIE Twitter @FIEfencing",
     "https://news.google.com/rss/search?q=FIEfencing+fencing&hl=en&gl=US&ceid=US:en"),
    # CyrusofChaos Facebook -- Google News indexes public posts
    ("SOCMINT: CyrusofChaos Facebook",
     "https://news.google.com/rss/search?q=CyrusofChaos+fencing&hl=en&gl=US&ceid=US:en"),
    # EFC Instagram @eurofencing
    ("SOCMINT: EFC Instagram",
     "https://news.google.com/rss/search?q=eurofencing+Instagram&hl=en&gl=US&ceid=US:en"),
    # FIE governance social commentary
    ("SOCMINT: FIE Usmanov ElHusseiny",
     "https://news.google.com/rss/search?q=Usmanov+fencing+2026&hl=en&gl=US&ceid=US:en"),
    ("SOCMINT: FIE ElHusseiny",
     "https://news.google.com/rss/search?q=ElHusseiny+fencing&hl=en&gl=US&ceid=US:en"),
]

# Nitter instances -- kept as best-effort; Twitter syndication API used as fallback
NITTER_ACCOUNTS = [
    ("EFC Twitter", "eurofencing"),
    ("FIE Twitter", "FIEfencing"),
]
NITTER_INSTANCES = [
    "https://nitter.privacyredirect.com",
    "https://nitter.poast.org",
    "https://nitter.cz",
    "https://nitter.1d4.us",
    "https://nitter.fdn.fr",
    "https://nitter.net",
    "https://lightbrd.com",
    "https://nitter.unixfox.eu",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

def strip_html(text):
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>',  ' ', text, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def fetch_html(label, url, max_chars=2500, verify_ssl=True):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        ctx = ssl.create_default_context()
        if not verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            raw = resp.read()
            enc = resp.headers.get("Content-Encoding", "")
            if enc == "gzip":
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8", errors="ignore")
        text = strip_html(text)
        return f"SOURCE: {label}\nURL: {url}\n{text[:max_chars]}"
    except Exception as e:
        return f"SOURCE: {label}\nURL: {url}\nERROR: {e}"

def fetch_rss(label, url, max_items=12):
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; EFC-Intel/1.0)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        items = re.findall(r'<item>(.*?)</item>', text, re.DOTALL)
        if not items:
            # Try atom feed format
            items = re.findall(r'<entry>(.*?)</entry>', text, re.DOTALL)
        results = []
        for item in items[:max_items]:
            title   = re.search(r'<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', item, re.DOTALL)
            link    = re.search(r'<link[^>]*href=["\']([^"\']+)["\']', item) or re.search(r'<link>(.*?)</link>', item, re.DOTALL)
            desc    = re.search(r'<description[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>', item, re.DOTALL) \
                   or re.search(r'<content[^>]*>(.*?)</content>', item, re.DOTALL) \
                   or re.search(r'<summary[^>]*>(.*?)</summary>', item, re.DOTALL)
            pubdate = re.search(r'<pubDate>(.*?)</pubDate>', item) or re.search(r'<published>(.*?)</published>', item)
            t = title.group(1).strip() if title else ""
            l = link.group(1).strip() if link else ""
            d = strip_html(desc.group(1))[:250] if desc else ""
            p = pubdate.group(1).strip() if pubdate else ""
            if t:
                results.append(f"  [{p}] {t}\n  {d}\n  URL: {l}")
        if results:
            return f"SOURCE: {label}\nURL: {url}\n" + "\n".join(results)
        else:
            return f"SOURCE: {label}\nURL: {url}\nNO ITEMS FOUND (feed empty or format unrecognised)"
    except Exception as e:
        return f"SOURCE: {label}\nURL: {url}\nERROR: {e}"

def fetch_twitter_syndication(handle, max_items=10):
    """Fetch recent tweets via Twitter's public syndication API (no auth needed)."""
    # Twitter's embed/syndication endpoint -- returns JSON for public accounts
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}?lang=en"
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
            "Accept": "application/json, text/html, */*",
            "Referer": f"https://twitter.com/{handle}",
        })
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        # Extract tweet text from the JSON/HTML response
        tweets = re.findall(r'"full_text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
        dates  = re.findall(r'"created_at"\s*:\s*"([^"]+)"', raw)
        if tweets:
            results = []
            for i, tweet in enumerate(tweets[:max_items]):
                tweet_clean = tweet.replace("\n", " ").replace('\"', '"')
                # Skip retweets of others
                if tweet_clean.startswith("RT @") and handle.lower() not in tweet_clean[:20].lower():
                    continue
                date = dates[i] if i < len(dates) else ""
                results.append(f"  [{date}] {tweet_clean[:280]}")
            if results:
                return f"SOCMINT SOURCE: @{handle} (Twitter syndication API)\n" + "\n".join(results)
    except Exception:
        pass
    return None

def fetch_nitter_rss(handle, instances, max_items=10):
    """Try multiple Nitter instances then fall back to Twitter syndication API."""
    for base in instances:
        url = f"{base}/{handle}/rss"
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            })
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            items = re.findall(r'<item>(.*?)</item>', text, re.DOTALL)
            if not items:
                continue
            results = []
            for item in items[:max_items]:
                title   = re.search(r'<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', item, re.DOTALL)
                link    = re.search(r'<link>(.*?)</link>', item, re.DOTALL)
                pubdate = re.search(r'<pubDate>(.*?)</pubDate>', item)
                t = strip_html(title.group(1)).strip() if title else ""
                l = link.group(1).strip() if link else ""
                p = pubdate.group(1).strip() if pubdate else ""
                if t:
                    results.append(f"  [{p}] {t}\n  URL: {l}")
            if results:
                return f"SOCMINT SOURCE: @{handle} via Nitter ({base})\n" + "\n".join(results)
        except Exception:
            continue
    # All Nitter instances failed -- try Twitter syndication API directly
    syndication = fetch_twitter_syndication(handle, max_items)
    if syndication:
        return syndication
    return f"SOCMINT SOURCE: @{handle} (Twitter/X)\nSTATUS: Nitter unreachable and syndication API unavailable -- no live tweet data"

print(f"Fetching sources...")
intel_chunks = []
source_log = []  # track what each source returned for diagnostics

for label, url in SOURCES:
    result = fetch_html(label, url, verify_ssl=True)
    intel_chunks.append(result)
    status = "ERROR" if "ERROR:" in result else f"{len(result)} chars"
    print(f"  {label}: {status}")
    source_log.append((label, url, "page", status))
    time.sleep(0.5)

for label, url in SSL_BYPASS_SOURCES:
    result = fetch_html(label, url, verify_ssl=False)
    intel_chunks.append(result)
    status = "ERROR" if "ERROR:" in result else f"{len(result)} chars"
    print(f"  {label}: {status}")
    source_log.append((label, url, "page-ssl-bypass", status))
    time.sleep(0.5)

for label, url in RSS_SOURCES:
    result = fetch_rss(label, url)
    intel_chunks.append(result)
    status = "ERROR" if "ERROR:" in result else ("NO ITEMS" if "NO ITEMS" in result else f"{result.count(chr(10))} lines")
    print(f"  {label}: {status}")
    source_log.append((label, url, "rss", status))
    time.sleep(0.5)

# SOCMINT RSS feeds
socmint_chunks = []
for label, url in SOCMINT_RSS:
    result = fetch_rss(label, url)
    socmint_chunks.append(result)
    status = "ERROR" if "ERROR:" in result else ("NO ITEMS" if "NO ITEMS" in result else f"{result.count(chr(10))} lines")
    print(f"  {label}: {status}")
    source_log.append((label, url, "socmint-rss", status))
    time.sleep(0.5)

# Nitter feeds for Twitter/X
for handle_label, handle in NITTER_ACCOUNTS:
    result = fetch_nitter_rss(handle, NITTER_INSTANCES)
    socmint_chunks.append(result)
    status = "OK" if "Nitter" in result and "STATUS:" not in result else "UNREACHABLE"
    print(f"  SOCMINT @{handle}: {status}")
    source_log.append((handle_label, f"twitter.com/{handle}", "nitter", status))
    time.sleep(0.5)

# Build source log string to inject into prompt
source_log_text = "\n".join(
    f"  [{stype}] {label} | {url} | {status}"
    for label, url, stype, status in source_log
)

intel_text = "\n\n".join(intel_chunks)
socmint_text = "\n\n".join(socmint_chunks)
print(f"Collected {len(intel_text)} chars intel, {len(socmint_text)} chars SOCMINT")

# ---- Step 2: Claude writes the HTML brief (NO tools, pure writing) ----------

BRIEF_SYSTEM = (
    "You are the EFC Intelligence Officer. TODAY IS " + TODAY + ". "
    "Your job: extract all relevant fencing intelligence from the raw source content below "
    "and write a professional HTML intelligence brief for the EFC Bureau. "
    "\n\nINSTRUCTIONS:"
    "\n- Extract every fact about EFC, FIE, competitions, governance, personnel from the sources."
    "\n- Apply NATO STANAG 2511 ratings:"
    "\n  eurofencing.info direct fetch = A-1; FIE official letters = A-1;"
    "\n  Sport&Politics/Francsjeux/Inquisitor = B-2; InsideTheGames = B-2;"
    "\n  British Fencing = B-2; FFE = B-2; Google News RSS = B-2;"
    "\n  SOCMINT Google News proxy = C-3; Nitter/Twitter syndication = C-3;"
    "\n  CyrusofChaos Facebook/Instagram = D-3."
    "\n- When a source label says 'via Google News', the rating applies to the "
    "underlying outlet (e.g. InsideTheGames via Google News = B-2)."
    "\n- Cite the source URL for every claim. Only name individuals in the sources."
    "\n- If a source returned an error or NO ITEMS, note it and move on."
    "\n- All recommendations go to EFC Bureau."
    "\n\nHTML REQUIREMENTS:"
    "\n- Return ONLY raw HTML with inline CSS. No markdown. No code fences."
    "\n- Every section must have real content. Do NOT write 'no intelligence found'."
    "\n- Use data from every source that returned content."
    "\n\nHTML STRUCTURE:"
    "\n<html><body style='font-family:Arial,sans-serif;margin:0;padding:0'>"
    "\n<table width='100%' cellpadding='0' cellspacing='0'>"
    "\n<tr><td style='background:#213389;padding:24px;text-align:center'>"
    "\n<div style='color:white;font-size:22px;font-weight:bold'>"
    "EUROPEAN FENCING CONFEDERATION</div>"
    "\n<div style='color:white;font-size:18px;font-weight:bold'>DAILY INTELLIGENCE BRIEF</div>"
    "\n<div style='color:#9DD1F4;font-size:13px;margin-top:6px'>" + TODAY + 
    " | Period: " + WEEK_AGO + " to " + TODAY + " | Classification: EFC BUREAU RESTRICTED</div>"
    "\n</td></tr></table>"
    "\nThen for each section use:"
    "\n<table width='100%'><tr><td style='background:#1a2970;padding:10px 20px'>"
    "<span style='color:white;font-weight:bold;font-size:14px'>SECTION TITLE</span></td></tr>"
    "\n<tr><td style='padding:15px 20px;color:#222'>CONTENT</td></tr></table>"
    "\n\nSECTIONS REQUIRED:"
    "\n1. BLUF - 2-3 sentence summary of most important intelligence"
    "\n2. KEY FINDINGS - HTML table: Rating | Source | Date | Finding"
    "\n   (minimum 4 rows of real findings from the intelligence provided)"
    "\n3. SOCMINT - social media intelligence section with two sub-tables:"
    "\n   TABLE A - Platform Activity (Platform | Handle | Date | Content Summary):"
    "\n   Use the SOCMINT-labelled sources. If Nitter returned posts, cite them (C-3)."
    "\n   If Nitter returned NO ITEMS or ERROR, use Google News SOCMINT sources instead."
    "\n   Always produce a row for each: EFC Twitter @eurofencing,"
    "\n   FIE Twitter @FIEfencing, CyrusofChaos Facebook, EFC Instagram @eurofencing."
    "\n   Ratings: Nitter C-3; Google News social C-3; Facebook/Instagram D-3."
    "\n   TABLE B - Social Narrative: one sentence per platform on tone and activity."
    "\n4. ASSESSMENT - analytical paragraph"
    "\n5. RECOMMENDATIONS TO EFC BUREAU - numbered list, min 3 items"
    "\n6. SOURCES ACCESSED - MANDATORY: include every single source from the fetch log."
    "\n   Table columns: Name | URL | Rating | Fetch Status"
    "\n   Copy the fetch status exactly from the log (e.g. '1234 chars', 'ERROR', 'NO ITEMS')."
    "\n   This table must include ALL entries from the log including FFE, SOCMINT sources, Nitter."
    "\n7. CONFIDENCE ASSESSMENT - paragraph"
    "\n</body></html>"
)

BRIEF_USER = (
    "=== COLLECTION METADATA ===\n"
    "Date: " + TODAY + " | Period: " + WEEK_AGO + " to " + TODAY + "\n"
    "Source fetch log:\n" + source_log_text + "\n\n"
    "=== MAIN INTELLIGENCE (from official portals, news, RSS) ===\n"
    + intel_text[:7000]
    + "\n\n=== SOCMINT INTELLIGENCE (from social media feeds and Nitter) ===\n"
    + socmint_text[:3000]
    + "\n\n=== INSTRUCTIONS ===\n"
    "Write the complete HTML brief now. "
    "Use EVERY source in the fetch log for the Sources Assessed table -- list ALL of them "
    "regardless of whether they returned data, with their actual status from the log. "
    "For SOCMINT: use any data from the SOCMINT section above. "
    "If a Nitter feed returned 'UNREACHABLE', note that status for that Twitter account. "
    "If Google News SOCMINT feeds returned items, use them as social intelligence. "
    "Do NOT write 'no data available' if there is relevant content in the sections above."
)

print("Calling Claude to write brief...")
for attempt in range(3):
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            system=BRIEF_SYSTEM,
            messages=[{"role": "user", "content": BRIEF_USER}],
        )
        break
    except anthropic.RateLimitError:
        print(f"Rate limit hit, waiting 60s (attempt {attempt+1})")
        if attempt < 2:
            time.sleep(60)
        else:
            raise

html = ""
for block in resp.content:
    if hasattr(block, "text") and len(block.text.strip()) > 200:
        html = block.text.strip()
        break

if html.startswith("```"):
    lines = html.splitlines()
    html = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

if not html or len(html) < 300:
    escaped = intel_text[:5000].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    html = (
        "<html><body style='font-family:Arial;margin:0'>"
        "<table width='100%'><tr>"
        "<td style='background:#213389;padding:20px;text-align:center'>"
        "<b style='color:white;font-size:18px'>EFC INTELLIGENCE BRIEF - " + TODAY + "</b>"
        "<br><span style='color:#9DD1F4;font-size:12px'>HTML generation failed - raw intel below</span>"
        "</td></tr><tr><td style='padding:20px'>"
        "<pre style='white-space:pre-wrap;font-size:11px'>" + escaped + "</pre>"
        "</td></tr></table></body></html>"
    )

# ---- Step 3: Send email -----------------------------------------------------

print(f"Sending email ({len(html)} chars HTML)...")
msg = MIMEMultipart("alternative")
msg["Subject"] = "EFC Intelligence Brief - " + TODAY
msg["From"]    = os.environ["GMAIL_ADDRESS"]
msg["To"]      = "evcann@fencing-efc.eu"
msg.attach(MIMEText(html, "html"))

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    s.sendmail(os.environ["GMAIL_ADDRESS"], "evcann@fencing-efc.eu", msg.as_string())

print("SUCCESS | " + TODAY + " | intel=" + str(len(intel_text)) + " | html=" + str(len(html)))
