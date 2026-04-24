"""Quick smoke test: send one SMS to a real number via Africa's Talking sandbox."""
from dotenv import load_dotenv
load_dotenv()

from agent.channels.sms import SMSChannel

ch = SMSChannel()
result = ch.send(
    to="+251920531543",
    body="Test from Tenacious Conversion Engine - sandbox smoke test.",
    warm_lead=True,
    synthetic=False,
)
print(result)
