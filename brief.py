import os, smtplib, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic

TODAY     = datetime.date.today().strftime("%d %B %Y")
WEEK_AGO  = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%d %B %Y")

SYSTEM = (
    "You are the EFC Intelligence Officer. TODAY IS " + TODAY + ". "
    "Produce a daily intelligence brief for the EFC Bureau. "
    "Rules: use web_search to collect live intelligence before writing; "
    "every claim needs a URL source; name only individuals traceable to a verified source; "
    "apply NATO STANAG 2511 source ratings (A-F reliability, 1-6 credibility) e.g. (A-1); "
    "all recommendations addressed to EFC Bureau; rate EFC Portal (eurofencing.info) as A-1. "
    "Mandatory search targets: eurofencing.info/news, fie.org/fie/documents/letters/2026, "
    "fie.org, the-inquisitor-magazine.com, sportandpolitics.de, francsjeux.com, "
    "insidethegames.biz, britishfencing.com, euromaidanpress.com. "
    "Return ONLY raw HTML with inline CSS. "
    "Use EFC blue #213389 header, white text, clean table layout. "
    "Sections: BLUF, Key Findings (rated table), Assessment, Recommendations to EFC Bureau, "
    "Sources, Confidence Assessment. No markdown fences, no preamble."
)

USER = (
    "EFC Daily Intelligence Brief for " + TODAY + ". "
    "Collection period: " + WEEK_AGO + " to " + TODAY + ". "
    "Search all mandatory targets listed in your instructions. "
    "After collecting intelligence, return the complete brief as raw HTML only."
)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

tools = [{"type": "web_search_20250305", "name": "web_search"}]

messages = [{"role": "user", "content": USER}]

# Agentic loop -- keep running until Claude stops calling tools
while True:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=SYSTEM,
        tools=tools,
        messages=messages,
    )

    # Append assistant turn
    messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "end_turn":
        break

    if response.stop_reason == "tool_use":
        # web_search executes server-side; acknowledge with tool_result
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Search completed."
                })
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        continue

    break  # unexpected stop_reason -- exit loop

# Extract final HTML text block
html = ""
for block in response.content:
    if hasattr(block, "text"):
        html = block.text.strip()
        break

# Strip any accidental markdown fences
if html.startswith("```"):
    lines = html.splitlines()
    html = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

if not html:
    html = "<p>No intelligence content generated.</p>"

# Send via Gmail SMTP
msg = MIMEMultipart("alternative")
msg["Subject"] = "EFC Intelligence Brief - " + TODAY
msg["From"]    = os.environ["GMAIL_ADDRESS"]
msg["To"]      = "evcann@fencing-efc.eu"
msg.attach(MIMEText(html, "html"))

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    s.sendmail(os.environ["GMAIL_ADDRESS"], "evcann@fencing-efc.eu", msg.as_string())

print("Brief sent successfully for " + TODAY)
