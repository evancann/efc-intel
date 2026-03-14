import os, smtplib, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import anthropic

TODAY = datetime.date.today().strftime("%d %B %Y")
WEEK_AGO = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%d %B %Y")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4000,
    system="You are the EFC Intelligence Officer. TODAY IS " + TODAY + ". Produce a daily intelligence brief for the EFC Bureau. Rules: every claim needs a URL; name only individuals traceable to a source; NATO STANAG 2511 ratings e.g. (A-1); all recommendations to EFC Bureau. Return raw HTML only with inline CSS, table layout, EFC blue #213389 header. Sections: BLUF, Key Findings, Assessment, Recommendations, Sources, Confidence. No markdown fences.",
    messages=[{"role": "user", "content": "EFC Daily Intelligence Brief for " + TODAY + ". Collection: " + WEEK_AGO + " to " + TODAY + ". Search: fie.org/fie/documents/letters/2026, eurofencing.info, fie.org, the-inquisitor-magazine.com, sportandpolitics.de, francsjeux.com, insidethegames.biz, britishfencing.com, euromaidanpress.com, facebook.com/CyrusofChaos. Return raw HTML only."}]
)

html = next(b.text for b in response.content if b.type == "text").strip()
if html.startswith("```"):
    lines = html.splitlines()
    html = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

msg = MIMEMultipart("alternative")
msg["Subject"] = "EFC Intelligence Brief - " + TODAY
msg["From"] = os.environ["GMAIL_ADDRESS"]
msg["To"] = "evcann@fencing-efc.eu"
msg.attach(MIMEText(html, "html"))

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
    s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    s.sendmail(os.environ["GMAIL_ADDRESS"], "evcann@fencing-efc.eu", msg.as_string())

print("Brief sent successfully")
