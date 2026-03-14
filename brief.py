import os, smtplib, datetime, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic

TODAY    = datetime.date.today().strftime("%d %B %Y")
WEEK_AGO = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%d %B %Y")

SYSTEM = (
    "You are the EFC Intelligence Officer. TODAY IS " + TODAY + ". "
    "Produce a daily intelligence brief for the EFC Bureau. "
    "Use web_search to collect live intelligence BEFORE writing the brief. "
    "Search at minimum: eurofencing.info news, fie.org letters 2026, sportandpolitics.de, "
    "francsjeux.com, the-inquisitor-magazine.com, insidethegames.biz fencing, "
    "britishfencing.com, euromaidanpress.com fencing. "
    "Apply NATO STANAG 2511 source ratings (A-F reliability, 1-6 credibility). "
    "Rate eurofencing.info EFC Portal as A-1. "
    "Every factual claim must cite a URL. Name only individuals traceable to a source. "
    "All recommendations are addressed to EFC Bureau. "
    "After searching, return ONLY a complete HTML document with inline CSS. "
    "Style: EFC blue #213389 full-width header, white bold text, clean sections. "
    "Sections: BLUF, Key Findings (HTML table with Rating/Source/Date/Detail columns), "
    "Assessment, Recommendations to EFC Bureau, Sources, Confidence Assessment. "
    "Do NOT return markdown. Do NOT return empty sections. "
    "The HTML must be complete and self-contained."
)

USER = (
    "Produce the EFC Daily Intelligence Brief for " + TODAY + ". "
    "Collection period: " + WEEK_AGO + " to " + TODAY + ". "
    "Search all mandatory sources now, then write the complete HTML brief."
)

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

tools = [{"type": "web_search_20250305", "name": "web_search"}]
messages = [{"role": "user", "content": USER}]

# Agentic loop
max_turns = 20
for _ in range(max_turns):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=6000,
        system=SYSTEM,
        tools=tools,
        messages=messages,
    )

    # Append assistant response
    messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "end_turn":
        break

    if response.stop_reason == "tool_use":
        # For web_search_20250305, the search results are returned IN the
        # tool_use block itself (server-side execution). We acknowledge each
        # tool_use block with a tool_result containing its output.
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                # Extract search results if present in the block
                result_content = "Search executed."
                if hasattr(block, "output") and block.output:
                    result_content = str(block.output)
                elif hasattr(block, "input") and isinstance(block.input, dict):
                    result_content = f"Searched for: {block.input.get('query', 'query')}"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_content,
                })
        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        continue

    break

# Extract HTML from final response
html = ""
for block in response.content:
    if hasattr(block, "text") and block.text.strip():
        html = block.text.strip()
        break

# Also check all messages for last text block (in case end_turn had prior tool calls)
if not html:
    for msg in reversed(messages):
        if msg["role"] == "assistant":
            content = msg["content"]
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "text") and block.text.strip():
                        html = block.text.strip()
                        break
            if html:
                break

# Strip accidental markdown fences
if html.startswith("```"):
    lines = html.splitlines()
    html = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])

# Fallback if still empty
if not html or len(html) < 200:
    html = (
        "<html><body style='font-family:Arial,sans-serif'>"
        "<div style='background:#213389;color:white;padding:20px;text-align:center'>"
        "<h1>EFC DAILY INTELLIGENCE BRIEF</h1>"
        "<p>" + TODAY + " | Collection error -- brief generation failed</p></div>"
        "<p style='padding:20px'>The brief generation produced no content. "
        "Check GitHub Actions logs for details.</p></body></html>"
    )

# Send email
msg = MIMEMultipart("alternative")
msg["Subject"] = "EFC Intelligence Brief - " + TODAY
msg["From"]    = os.environ["GMAIL_ADDRESS"]
msg["To"]      = "evcann@fencing-efc.eu"
msg.attach(MIMEText(html, "html"))

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    s.sendmail(os.environ["GMAIL_ADDRESS"], "evcann@fencing-efc.eu", msg.as_string())

print("Brief sent for " + TODAY + " | HTML length: " + str(len(html)))
