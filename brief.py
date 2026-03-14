import os, smtplib, datetime, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic

TODAY    = datetime.date.today().strftime("%d %B %Y")
WEEK_AGO = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%d %B %Y")

# --- Step 1: collect raw intelligence via Anthropic web search in a SEPARATE call ---
# We ask Claude to search and return a plain text intelligence dump first.
# This keeps the token count predictable and avoids multi-turn tool loops.

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

COLLECTION_SYSTEM = (
    "You are an intelligence collector. Use web_search to gather raw information. "
    "Search these queries one by one: "
    "(1) eurofencing.info news March 2026, "
    "(2) FIE fencing governance news 2026, "
    "(3) European fencing championship 2026, "
    "(4) sportandpolitics.de fencing 2026. "
    "After all searches, return a plain text summary of every fact found, "
    "with the source URL for each fact. No HTML. No analysis. Just facts and URLs."
)

COLLECTION_USER = "Collect intelligence for " + TODAY + ". Search all four queries now."

tools = [{"type": "web_search_20250305", "name": "web_search"}]
messages = [{"role": "user", "content": COLLECTION_USER}]

def api_call(msgs, sys, max_tok=2000, use_tools=True):
    for attempt in range(3):
        try:
            kwargs = dict(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tok,
                system=sys,
                messages=msgs,
            )
            if use_tools:
                kwargs["tools"] = tools
            return client.messages.create(**kwargs)
        except anthropic.RateLimitError:
            if attempt < 2:
                time.sleep(60)
            else:
                raise

# Run collection loop
for _ in range(15):
    resp = api_call(messages, COLLECTION_SYSTEM, max_tok=2000, use_tools=True)
    messages.append({"role": "assistant", "content": resp.content})

    if resp.stop_reason == "end_turn":
        break

    if resp.stop_reason == "tool_use":
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Search executed.",
                })
        messages.append({"role": "user", "content": results})
        continue
    break

# Extract collected intelligence text
intel_text = ""
for block in resp.content:
    if hasattr(block, "text") and block.text.strip():
        intel_text = block.text.strip()
        break

if not intel_text:
    intel_text = "No intelligence collected from web searches."

# --- Step 2: write the HTML brief from the collected intelligence ---
BRIEF_SYSTEM = (
    "You are the EFC Intelligence Officer. TODAY IS " + TODAY + ". "
    "Write a complete HTML intelligence brief for the EFC Bureau using the raw intelligence provided. "
    "Apply NATO STANAG 2511 ratings (A-F reliability, 1-6 credibility). "
    "Rate eurofencing.info as A-1. Cite every claim with its source URL. "
    "Name only individuals that appear in the source material. "
    "All recommendations go to EFC Bureau. "
    "Return ONLY complete raw HTML with inline CSS. No markdown. "
    "HEADER: full-width table row, background-color:#213389, white bold centered text, "
    "two lines: 'EUROPEAN FENCING CONFEDERATION DAILY INTELLIGENCE BRIEF' and date/period. "
    "SECTIONS (each with a #213389 dark blue subheader row): "
    "1. BLUF (2-3 sentence summary), "
    "2. Key Findings (HTML table: Rating | Source | Date | Detail), "
    "3. Assessment, "
    "4. Recommendations to EFC Bureau (numbered list), "
    "5. Sources (table: Source | URL | Rating | Last accessed), "
    "6. Confidence Assessment. "
    "All sections must have substantive content based on the intelligence provided."
)

BRIEF_USER = (
    "Raw intelligence collected for " + TODAY + " (period " + WEEK_AGO + " to " + TODAY + "):\n\n"
    + intel_text
    + "\n\nNow write the complete HTML brief."
)

brief_resp = api_call(
    [{"role": "user", "content": BRIEF_USER}],
    BRIEF_SYSTEM,
    max_tok=4000,
    use_tools=False,
)

html = ""
for block in brief_resp.content:
    if hasattr(block, "text") and len(block.text.strip()) > 100:
        html = block.text.strip()
        break

# Strip markdown fences
if html.startswith("```"):
    lines = html.splitlines()
    html = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

# Fallback
if not html or len(html) < 200:
    html = (
        "<html><body style='font-family:Arial,sans-serif;margin:0'>"
        "<table width='100%' cellpadding='0' cellspacing='0'><tr>"
        "<td style='background:#213389;padding:20px;text-align:center'>"
        "<p style='color:white;font-size:20px;font-weight:bold;margin:0'>"
        "EUROPEAN FENCING CONFEDERATION DAILY INTELLIGENCE BRIEF</p>"
        "<p style='color:#9DD1F4;margin:5px 0 0'>" + TODAY + " | Generation failed</p>"
        "</td></tr><tr><td style='padding:20px'>"
        "<p>Brief generation failed. Check GitHub Actions logs.</p>"
        "<pre>" + intel_text[:500] + "</pre>"
        "</td></tr></table></body></html>"
    )

# --- Step 3: send email ---
msg = MIMEMultipart("alternative")
msg["Subject"] = "EFC Intelligence Brief - " + TODAY
msg["From"]    = os.environ["GMAIL_ADDRESS"]
msg["To"]      = "evcann@fencing-efc.eu"
msg.attach(MIMEText(html, "html"))

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    s.sendmail(os.environ["GMAIL_ADDRESS"], "evcann@fencing-efc.eu", msg.as_string())

print("Sent | " + TODAY + " | intel chars: " + str(len(intel_text)) + " | HTML chars: " + str(len(html)))
