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

SOURCES = [
    ("FIE Letters 2026",  "https://fie.org/fie/documents/letters/2026"),
    ("FIE News",          "https://fie.org/articles"),
    ("Sport&Politics",    "https://www.sportandpolitics.de"),
    ("Francsjeux EN",     "https://www.francsjeux.com/en"),
    ("The Inquisitor",    "https://www.the-inquisitor-magazine.com"),
]

# Sources requiring SSL bypass (self-signed or expired cert)
SSL_BYPASS_SOURCES = [
    ("EFC Portal News",   "https://www.eurofencing.info/news"),
]

RSS_SOURCES = [
    # British Fencing -- RSS avoids JS rendering issue
    ("British Fencing News",
     "https://www.britishfencing.com/feed/"),
    # InsideTheGames -- RSS avoids 403 bot block on search page
    ("InsideTheGames Fencing",
     "https://www.insidethegames.biz/rss/sport/fencing"),
    # Google News -- EFC/FIE governance
    ("Google News EFC FIE",
     "https://news.google.com/rss/search?q=EFC+FIE+fencing+European&hl=en&gl=US&ceid=US:en"),
    # Google News -- fencing championships
    ("Google News Fencing 2026",
     "https://news.google.com/rss/search?q=fencing+championship+2026&hl=en&gl=US&ceid=US:en"),
    # Google News -- EFC social/comms picked up by press
    ("Google News EFC Social",
     "https://news.google.com/rss/search?q=%22European+Fencing+Confederation%22+OR+eurofencing&hl=en&gl=US&ceid=US:en"),
    # Google News -- CyrusofChaos + Usmanov FIE commentary
    ("Google News CyrusofChaos FIE",
     "https://news.google.com/rss/search?q=CyrusofChaos+OR+%22Usmanov%22+fencing&hl=en&gl=US&ceid=US:en"),
    # Nitter (public X/Twitter mirror) -- EFC official account
    ("EFC Twitter via Nitter",
     "https://nitter.poast.org/eurofencing/rss"),
    # Nitter -- FIE official account
    ("FIE Twitter via Nitter",
     "https://nitter.poast.org/FIEfencing/rss"),
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
        req = urllib.request.Request(url, headers={"User-Agent": "EFC-Intel/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        items = re.findall(r'<item>(.*?)</item>', text, re.DOTALL)
        results = []
        for item in items[:max_items]:
            title = re.search(r'<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', item, re.DOTALL)
            link  = re.search(r'<link>(.*?)</link>', item, re.DOTALL)
            desc  = re.search(r'<description[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>', item, re.DOTALL)
            pubdate = re.search(r'<pubDate>(.*?)</pubDate>', item)
            t = title.group(1).strip() if title else ""
            l = link.group(1).strip() if link else ""
            d = strip_html(desc.group(1))[:200] if desc else ""
            p = pubdate.group(1).strip() if pubdate else ""
            results.append(f"  [{p}] {t} | {l}\n  {d}")
        return f"SOURCE: {label}\nURL: {url}\n" + "\n".join(results)
    except Exception as e:
        return f"SOURCE: {label}\nURL: {url}\nERROR: {e}"

print(f"Fetching {len(SOURCES)} pages, {len(SSL_BYPASS_SOURCES)} SSL-bypass pages, and {len(RSS_SOURCES)} RSS feeds...")
intel_chunks = []

for label, url in SOURCES:
    intel_chunks.append(fetch_html(label, url, verify_ssl=True))
    time.sleep(0.5)

for label, url in SSL_BYPASS_SOURCES:
    intel_chunks.append(fetch_html(label, url, verify_ssl=False))
    time.sleep(0.5)

for label, url in RSS_SOURCES:
    intel_chunks.append(fetch_rss(label, url))
    time.sleep(0.5)

intel_text = "\n\n".join(intel_chunks)
print(f"Collected {len(intel_text)} chars of raw intelligence")

# ---- Step 2: Claude writes the HTML brief (NO tools, pure writing) ----------

BRIEF_SYSTEM = (
    "You are the EFC Intelligence Officer. TODAY IS " + TODAY + ". "
    "Your job: extract all relevant fencing intelligence from the raw source content below "
    "and write a professional HTML intelligence brief for the EFC Bureau. "
    "\n\nINSTRUCTIONS:"
    "\n- Extract every fact about EFC, FIE, competitions, governance, personnel from the sources."
    "\n- Apply NATO STANAG 2511 ratings: eurofencing.info = A-1, FIE official letters = A-1, "
    "InsideTheGames/BritishFencing = B-2, Google News/press = B-2, "
    "Nitter/Twitter = C-3, social media/CyrusofChaos = D-3, unverified = D-4."
    "\n- Cite the source URL for every claim. Only name individuals who appear in the sources."
    "\n- If a source returned an error, note it and move on."
    "\n- All recommendations go to EFC Bureau."
    "\n- Include a dedicated SOCMINT sub-section under Key Findings for any social media "
    "intelligence from Twitter/Nitter, Facebook references, Instagram, or CyrusofChaos. "
    "Label social media entries clearly with platform and handle."
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
    "\n3. SOCMINT - social media intelligence table: Platform | Handle | Date | Finding"
    "\n   Pull from Nitter feeds (@eurofencing, @FIEfencing) and any Google News social refs."
    "\n   Always include rows for: EFC Twitter, FIE Twitter, CyrusofChaos Facebook, EFC Instagram."
    "\n   If a platform was inaccessible, note that in the Finding column."
    "\n4. ASSESSMENT - analytical paragraph"
    "\n5. RECOMMENDATIONS TO EFC BUREAU - numbered list, min 3 items"
    "\n6. SOURCES ACCESSED - table: Name | URL | Rating | Status"
    "\n7. CONFIDENCE ASSESSMENT - paragraph"
    "\n</body></html>"
)

BRIEF_USER = (
    "Raw intelligence collected on " + TODAY + 
    " (collection period: " + WEEK_AGO + " to " + TODAY + "):\n\n"
    + intel_text[:10000]
    + "\n\nWrite the complete HTML brief now. Extract and use every relevant fact from the above."
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
