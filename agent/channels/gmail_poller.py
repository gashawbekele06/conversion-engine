"""Gmail IMAP poller — PATH A real-email reply detection.

Watches for new emails addressed TO ``TENACIOUS_REPLY_TO`` (a Gmail plus
address such as ``gashawbekelek+tenacious@gmail.com``) and fires the
registered ``_email_reply_handlers`` in ``agent.webhooks``.

Why plus-addressing instead of a custom domain?
  A custom Resend inbound domain requires DNS delegation and a public URL.
  Gmail plus-addressing is zero-config: mail to
  ``gashawbekelek+tenacious@gmail.com`` lands directly in the
  ``gashawbekelek@gmail.com`` inbox. No DNS change needed.

Setup (one-time):
  1. Go to https://myaccount.google.com/apppasswords
  2. Generate an App Password for "Mail" / "Other" → name it "tenacious"
  3. Set in .env:
       GMAIL_IMAP_USER=gashawbekelek@gmail.com
       GMAIL_IMAP_APP_PASSWORD=xxxx xxxx xxxx xxxx   (16 chars, spaces ok)
       TENACIOUS_REPLY_TO=gashawbekelek+tenacious@gmail.com

Usage (from orchestrator or API server):
  from agent.channels.gmail_poller import GmailPoller
  poller = GmailPoller()
  poller.start()          # daemon thread, polls every 15 s
  ...
  poller.stop()

Or run standalone for testing:
  python -m agent.channels.gmail_poller
"""
from __future__ import annotations

import email as _email_lib
import imaplib
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default poll interval in seconds.  Short enough to feel real-time in a demo.
_DEFAULT_INTERVAL = 15

# Folder to search in
_IMAP_FOLDER = "INBOX"

# Persistent marker — last UID we processed, written to disk so restarts don't
# reprocess old mail.
_SEEN_FILE = Path(__file__).resolve().parents[2] / "eval" / "traces" / "gmail_poller_seen.txt"


def _read_last_uid() -> str | None:
    try:
        text = _SEEN_FILE.read_text(encoding="utf-8").strip()
        return text if text else None
    except FileNotFoundError:
        return None


def _write_last_uid(uid: str) -> None:
    _SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SEEN_FILE.write_text(uid + "\n", encoding="utf-8")


class GmailPoller:
    """Thread-based IMAP poller for Gmail plus-address inbound replies.

    Parameters
    ----------
    interval:
        Poll interval in seconds (default 15).
    reply_to_address:
        The plus-address we expect replies TO, e.g.
        ``gashawbekelek+tenacious@gmail.com``.  Defaults to
        ``TENACIOUS_REPLY_TO`` env var.
    imap_user:
        Gmail account, e.g. ``gashawbekelek@gmail.com``.
        Defaults to ``GMAIL_IMAP_USER`` env var.
    imap_password:
        Gmail App Password (16 chars, spaces stripped).
        Defaults to ``GMAIL_IMAP_APP_PASSWORD`` env var.
    """

    def __init__(
        self,
        *,
        interval: int = _DEFAULT_INTERVAL,
        reply_to_address: str | None = None,
        imap_user: str | None = None,
        imap_password: str | None = None,
    ) -> None:
        self.interval = interval
        self.reply_to_address = (
            reply_to_address
            or os.getenv("TENACIOUS_REPLY_TO", "")
        ).lower().strip()
        self.imap_user = (imap_user or os.getenv("GMAIL_IMAP_USER", "")).strip()
        self.imap_password = (
            imap_password or os.getenv("GMAIL_IMAP_APP_PASSWORD", "")
        ).replace(" ", "").strip()

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_poll: float | None = None
        self._last_error: str | None = None
        self._emails_detected: int = 0
        self._started_at: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return True when all three required env vars are set."""
        return bool(self.reply_to_address and self.imap_user and self.imap_password)

    def start(self) -> None:
        """Start the polling daemon thread."""
        if not self.is_configured():
            logger.warning(
                "GmailPoller not started — missing env vars. "
                "Set GMAIL_IMAP_USER, GMAIL_IMAP_APP_PASSWORD, TENACIOUS_REPLY_TO."
            )
            return
        if self._thread and self._thread.is_alive():
            logger.debug("GmailPoller already running.")
            return
        self._stop_event.clear()
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._run,
            name="gmail-poller",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "GmailPoller started — watching %s for replies to %s (interval=%ds)",
            self.imap_user,
            self.reply_to_address,
            self.interval,
        )

    def stop(self) -> None:
        """Signal the polling thread to stop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("GmailPoller stopped.")

    def status(self) -> dict[str, Any]:
        """Return a JSON-serialisable status dict for the dashboard."""
        running = bool(self._thread and self._thread.is_alive())
        return {
            "running": running,
            "configured": self.is_configured(),
            "reply_to": self.reply_to_address or None,
            "imap_user": self.imap_user or None,
            "interval_s": self.interval,
            "last_poll_ts": self._last_poll,
            "last_poll_ago_s": round(time.time() - self._last_poll, 1) if self._last_poll else None,
            "emails_detected": self._emails_detected,
            "last_error": self._last_error,
            "started_at": self._started_at,
        }

    # ------------------------------------------------------------------
    # Internal polling loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
                self._last_error = None
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                logger.error("GmailPoller error: %s", exc)
            self._last_poll = time.time()
            self._stop_event.wait(self.interval)

    def _poll_once(self) -> None:
        """Connect to IMAP, search for new replies, dispatch handlers."""
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        try:
            mail.login(self.imap_user, self.imap_password)
            mail.select(_IMAP_FOLDER, readonly=False)

            # Search for messages addressed TO our reply-to plus address.
            # We combine with UNSEEN so we only process new messages.
            # Gmail IMAP supports TO search with full RFC 5321 address.
            search_criteria = f'(UNSEEN TO "{self.reply_to_address}")'
            status, data = mail.uid("SEARCH", None, search_criteria)
            if status != "OK":
                return

            uid_bytes = data[0]
            if not uid_bytes:
                return
            uids = uid_bytes.split()
            if not uids:
                return

            last_uid = _read_last_uid()

            for uid_b in uids:
                uid_str = uid_b.decode()

                # Skip UIDs we've already processed across restarts.
                if last_uid and int(uid_str) <= int(last_uid):
                    continue

                msg = self._fetch_message(mail, uid_b)
                if msg is None:
                    continue

                self._dispatch(msg, uid_str)
                _write_last_uid(uid_str)
                self._emails_detected += 1

                # Mark as SEEN so UNSEEN search won't re-surface it.
                mail.uid("STORE", uid_b, "+FLAGS", "\\Seen")

        finally:
            try:
                mail.logout()
            except Exception:  # noqa: BLE001
                pass

    def _fetch_message(self, mail: imaplib.IMAP4_SSL, uid: bytes):
        """Fetch and parse an email message. Returns None on failure."""
        status, data = mail.uid("FETCH", uid, "(RFC822)")
        if status != "OK" or not data or data[0] is None:
            return None
        raw = data[0][1] if isinstance(data[0], tuple) else None
        if not raw:
            return None
        return _email_lib.message_from_bytes(raw)

    def _dispatch(self, msg, uid_str: str) -> None:
        """Extract fields, classify, and fire registered reply handlers."""
        from_raw = msg.get("From", "")
        from_addr = _parse_email_address(from_raw)
        subject = _decode_header(msg.get("Subject", ""))
        body_text = _extract_body(msg)

        logger.info(
            "GmailPoller: new reply UID=%s from=%s subject=%r",
            uid_str, from_addr, subject
        )

        # Classify
        lower_body = body_text.lower()
        if any(w in lower_body for w in (
            "unsubscribe", "opt out", "opt-out", "remove me", "stop emailing"
        )):
            kind = "unsubscribe"
        elif any(w in lower_body for w in (
            "interested", "tell me more", "yes", "sure", "sounds good",
            "let's talk", "love to chat", "worth a call", "30 minutes",
            "schedule", "book", "calendar", "worth a", "happy to",
        )):
            kind = "reply_positive"
        elif any(w in lower_body for w in (
            "not interested", "no thanks", "not right now", "pass",
        )):
            kind = "reply_negative"
        else:
            kind = "reply_other"

        logger.info("GmailPoller: classified as %r", kind)

        # Build a flat payload matching the webhook handler contract
        payload = {
            "from": from_addr,
            "subject": subject,
            "text": body_text,
            "uid": uid_str,
            "source": "gmail_imap",
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        # Append to inbox log (same path as webhook handler)
        _append_inbox(payload, kind)

        # Dispatch to all registered handlers
        from agent.webhooks import _email_reply_handlers
        for handler in _email_reply_handlers:
            try:
                handler(kind=kind, from_addr=from_addr, subject=subject, payload=payload)
            except Exception as exc:  # noqa: BLE001
                logger.error("GmailPoller handler error: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_email_address(raw: str) -> str:
    """Extract bare email from 'Name <email@example.com>' or plain string."""
    if not raw:
        return ""
    m = re.search(r"<([^>]+)>", raw)
    return m.group(1).strip() if m else raw.strip()


def _decode_header(raw: str) -> str:
    """Decode RFC 2047 encoded email header into a plain string."""
    if not raw:
        return ""
    import email.header
    parts = []
    for decoded, charset in _email_lib.header.decode_header(raw):
        if isinstance(decoded, bytes):
            parts.append(decoded.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(decoded)
    return "".join(parts)


def _extract_body(msg) -> str:
    """Extract plain-text body from a parsed email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = part.get("Content-Disposition", "")
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset("utf-8") or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset("utf-8") or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def _append_inbox(payload: dict, kind: str) -> None:
    """Append to eval/traces/inbox.jsonl for audit trail."""
    import json
    inbox_path = Path(__file__).resolve().parents[2] / "eval" / "traces" / "inbox.jsonl"
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "channel": "email",
        "ts": time.time(),
        "from": payload.get("from", ""),
        "subject": payload.get("subject", ""),
        "kind": kind,
        "source": "gmail_imap",
        "payload": payload,
    }
    with inbox_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


# ---------------------------------------------------------------------------
# Singleton — one poller per process
# ---------------------------------------------------------------------------

_poller: GmailPoller | None = None


def get_poller() -> GmailPoller:
    """Return the process-level singleton poller (creates if needed)."""
    global _poller
    if _poller is None:
        _poller = GmailPoller()
    return _poller


# ---------------------------------------------------------------------------
# Standalone test mode
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)
    except ImportError:
        pass

    p = GmailPoller()
    if not p.is_configured():
        print("ERROR: Missing env vars. Set GMAIL_IMAP_USER, GMAIL_IMAP_APP_PASSWORD, TENACIOUS_REPLY_TO")
        sys.exit(1)

    print(f"Polling {p.imap_user} for replies to {p.reply_to_address} …")
    print("Send a reply to that address from Gmail, then watch here.")
    print("Ctrl+C to stop.\n")

    p.start()
    try:
        while True:
            time.sleep(5)
            s = p.status()
            print(f"  last_poll={s['last_poll_ago_s']}s ago  detected={s['emails_detected']}  error={s['last_error']}")
    except KeyboardInterrupt:
        p.stop()
