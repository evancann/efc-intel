import os, smtplib, datetime, time, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import urllib.request, urllib.parse, urllib.error
import anthropic

TODAY    = datetime.date.today().strftime("%d %B %Y")
WEEK_AGO = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%d %B %Y")

# -- Step 1: collect raw intelligence via direct web searches ------------------

SEARCH_QUERIES = [
    "eurofencing.info news fencing 2026",
    "FIE fencing governance news March 2026",
    "European fencing championship 2026",
    "sportandpolitics.de fencing Usmanov 2026",
    "FIE Usmanov ElHusseiny fencing news 2026",
]

def brave_search(query, api_key, num=5):
    """Search using Brave Search API and return snippet text."""
    url = "https://api.search.brave.com/res/v1/web/search"
    params = urllib.parse.urlencode({"q": query, "count": num, "text_decorations": "0"})
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = []
        for item in data.get("web", {}).get("results", []):
            title   = item.get("title", "")
            url_val = item.get("url", "")
            snippet = item.get("description", "")
            age     = item.get("age", "")
            results.append(f"TITLE: {title}\nURL: {url_val}\nDATE: {age}\nSNIPPET: {snippet}")
        return "\n\n".join(results) if results else "No results."
    except Exception as e:
        return f"Search error: {e}"

def duckduckgo_search(query, num=5):
    """Fallback: DuckDuckGo instant answers (no API key needed)."""
    url = "https://api.duckduckgo.com/"
    params = urllib.parse.urlencode({
        "q": query, "format": "json", "no_html": "1", "skip_disambig": "1"
    })
    try:
        req = urllib.request.Request(
            f"{url}?{params}",
            headers={"User-Agent": "EFC-Intel-Bot/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = []
        abstract = data.get("AbstractText", "")
        abstract_url = data.get("AbstractURL", "")
        if abstract:
            results.append(f"ABSTRACT: {abstract}\nURL: {abstract_url}")
        for topic in data.get("RelatedTopics", [])[:num]:
            if isinstance(topic, dict) and "Text" in topic:
                results.append(f"TOPIC: {topic.get('Text','')}\nURL: {topic.get('FirstURL','')}")
        return "\n\n".join(results) if results else "No results."
    except Exception as e:
        return f"Search error: {e}"

# Collect intelligence
brave_key = os.environ.get("BRAVE_API_KEY", "")
intel_chunks = []

for query in SEARCH_QUERIES:
    time.sleep(1)  # polite delay
    if brave_key:
        result = brave_search(query, brave_key)
    else:
        result = duckduckgo_search(query)
    intel_chunks.append(f"=== QUERY: {query} ===\n{result}")

intel_text = "\n\n".join(intel_chunks)

# -- Step 2: write the HTML brief from collected intelligence ------------------

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

BRIEF_SYSTEM = (
    "You are the EFC Intelligence Officer. TODAY IS " + TODAY + ". "
    "Write a complete HTML intelligence brief for the EFC Bureau "
    "using ONLY the raw search intelligence provided in the user message. "
    "Apply NATO STANAG 2511 ratings (A-F reliability, 1-6 credibility). "
    "Rate eurofencing.info as A-1. Cite every claim with its source URL. "
    "Name only individuals that appear in the provided source material. "
    "All recommendations go to EFC Bureau. "
    "Return ONLY complete raw HTML with inline CSS -- no markdown, no fences, no preamble. "
    "REQUIRED HTML STRUCTURE:\n"
    "<html><body style='font-family:Arial,sans-serif;margin:0;padding:0'>\n"
    "<!-- Full-width EFC blue header -->\n"
    "<table width='100%'...> with background #213389, white text: title + date/period\n"
    "<!-- Each section has a subheader row background #1a2970, white text -->\n"
    "Section 1: BLUF (2-3 sentences of real intelligence)\n"
    "Section 2: Key Findings (HTML table, columns: Rating | Source | Date | Detail -- "
    "must have at least 3 rows of real findings)\n"
    "Section 3: Assessment (paragraph of real analysis)\n"
    "Section 4: Recommendations to EFC Bureau (numbered list, minimum 3 items)\n"
    "Section 5: Sources (table: Source Name | URL | Rating | Date)\n"
    "Section 6: Confidence Assessment\n"
    "</body></html>"
)

BRIEF_USER = (
    "Raw intelligence collected " + TODAY + " (period " + WEEK_AGO + " to " + TODAY + "):\n\n"
    + intel_text[:8000]  # cap to avoid token limits
    + "\n\nWrite the complete HTML brief now. Every section must contain real content from the above intelligence."
)

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
        if attempt < 2:
            time.sleep(60)
        else:
            raise

html = ""
for block in resp.content:
    if hasattr(block, "text") and len(block.text.strip()) > 200:
        html = block.text.strip()
        break

# Strip fences
if html.startswith("```"):
    lines = html.splitlines()
    html = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

# Fallback with intel dump so at least the data is visible
if not html or len(html) < 300:
    escaped = intel_text[:3000].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    html = (
        "<html><body style='font-family:Arial,sans-serif;margin:0'>"
        "<table width='100%'><tr><td style='background:#213389;padding:20px;text-align:center'>"
        "<p style='color:white;font-size:18px;font-weight:bold;margin:0'>"
        "EUROPEAN FENCING CONFEDERATION DAILY INTELLIGENCE BRIEF</p>"
        "<p style='color:#9DD1F4;margin:4px 0 0'>" + TODAY + " | HTML generation failed</p>"
        "</td></tr><tr><td style='padding:20px'>"
        "<h3>Raw Intelligence Collected (fallback display):</h3>"
        "<pre style='white-space:pre-wrap;font-size:12px'>" + escaped + "</pre>"
        "</td></tr></table></body></html>"
    )

# -- Step 3: send email --------------------------------------------------------

msg = MIMEMultipart("alternative")
msg["Subject"] = "EFC Intelligence Brief - " + TODAY
msg["From"]    = os.environ["GMAIL_ADDRESS"]
msg["To"]      = "evcann@fencing-efc.eu"
msg.attach(MIMEText(html, "html"))

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    s.sendmail(os.environ["GMAIL_ADDRESS"], "evcann@fencing-efc.eu", msg.as_string())

print("Sent | " + TODAY + " | intel: " + str(len(intel_text)) + " chars | html: " + str(len(html)) + " chars")
