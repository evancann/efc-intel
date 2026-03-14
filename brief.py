import os, smtplib, datetime, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic

TODAY    = datetime.date.today().strftime("%d %B %Y")
WEEK_AGO = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%d %B %Y")

SYSTEM = (
    "You are the EFC Intelligence Officer. TODAY IS " + TODAY + ". "
    "Use web_search to collect intelligence, then write a complete HTML intelligence brief. "
    "Search these targets: eurofencing.info news, fie.org fencing news 2026, "
    "FIE governance fencing 2026, European fencing championship 2026. "
    "Apply NATO STANAG 2511 ratings. Rate eurofencing.info as A-1. "
    "Cite every claim with a URL. Name only verified individuals. "
    "Recommendations go to EFC Bureau. "
    "Return ONLY complete raw HTML with inline CSS. "
    "Header: full-width, background #213389, white bold text, centered. "
    "Sections: BLUF, Key Findings table (Rating/Source/Date/Detail), "
    "Assessment, Recommendations to EFC Bureau, Sources, Confidence. "
    "No markdown. No empty sections. Complete self-contained HTML."
)

USER = (
    "EFC Daily Intelligence Brief for " + TODAY + ". "
    "Period: " + WEEK_AGO + " to " + TODAY + ". "
    "Search now then return the complete HTML brief."
)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
tools  = [{"type": "web_search_20250305", "name": "web_search"}]

def call_with_retry(messages, max_retries=3):
    for attempt in range(max_retries):
        try:
            return client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                system=SYSTEM,
                tools=tools,
                messages=messages,
            )
        except anthropic.RateLimitError:
            if attempt < max_retries - 1:
                time.sleep(60)
            else:
                raise

messages = [{"role": "user", "content": USER}]

# Agentic loop -- max 10 turns to avoid runaway token usage
html = ""
for turn in range(10):
    response = call_with_retry(messages)
    messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "end_turn":
        for block in response.content:
            if hasattr(block, "text") and len(block.text.strip()) > 200:
                html = block.text.strip()
                break
        break

    if response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Search completed successfully.",
                })
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        continue

    break

# Strip markdown fences if present
if html.startswith("```"):
    lines = html.splitlines()
    html = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

# Fallback
if not html or len(html) < 200:
    html = (
        "<html><body style='font-family:Arial,sans-serif;margin:0'>"
        "<table width='100%'><tr><td style='background:#213389;padding:20px;text-align:center'>"
        "<h1 style='color:white;margin:0'>EUROPEAN FENCING CONFEDERATION</h1>"
        "<h2 style='color:white;margin:5px 0'>DAILY INTELLIGENCE BRIEF</h2>"
        "<p style='color:#9DD1F4;margin:0'>" + TODAY + " | Generation failed -- check logs</p>"
        "</td></tr><tr><td style='padding:20px'>"
        "<p>Brief generation produced no content. Check GitHub Actions logs.</p>"
        "</td></tr></table></body></html>"
    )

# Send
msg = MIMEMultipart("alternative")
msg["Subject"] = "EFC Intelligence Brief - " + TODAY
msg["From"]    = os.environ["GMAIL_ADDRESS"]
msg["To"]      = "evcann@fencing-efc.eu"
msg.attach(MIMEText(html, "html"))

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    s.sendmail(os.environ["GMAIL_ADDRESS"], "evcann@fencing-efc.eu", msg.as_string())

print("Sent | " + TODAY + " | HTML chars: " + str(len(html)))
