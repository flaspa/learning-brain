"""Parse a WhatsApp "Messages to yourself" export into normalized URL records.

See CLAUDE.md for the parsing requirements this implements.
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SENDER = "Flavia Sparacino"
SOURCE = "whatsapp_self_chat"
ADJACENCY_WINDOW = timedelta(minutes=5)
MEDIA_OMITTED = "<Media omitted>"

DEFAULT_INPUT = Path("data/whatsapp/whatsApp_chat_flavspa.txt")
DEFAULT_OUTPUT = Path("output/whatsapp_links.json")

# Accept a plain space, NBSP, or narrow no-break space before AM/PM, since
# different WhatsApp export locales/versions vary here.
MESSAGE_START_RE = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}), "
    r"(?P<time>\d{1,2}:\d{2})[ \xa0 ]?(?P<ampm>[AP]M) - (?P<rest>.*)$"
)
URL_RE = re.compile(r"https?://\S+|(?<![\w.])www\.\S+")


class ParseWarning:
    def __init__(self, line_no, message):
        self.line_no = line_no
        self.message = message

    def __str__(self):
        return f"line {self.line_no}: {self.message}"


def parse_timestamp(date_str, time_str, ampm):
    month, day, year = (int(part) for part in date_str.split("/"))
    if year < 100:
        year += 2000
    hour, minute = (int(part) for part in time_str.split(":"))
    if ampm == "AM":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return datetime(year, month, day, hour, minute)


def read_raw_messages(path):
    """Group raw lines into logical (possibly multiline) messages."""
    messages = []
    warnings = []
    current = None

    with path.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip("\n")
            match = MESSAGE_START_RE.match(line)
            if match:
                if current is not None:
                    messages.append(current)
                current = {
                    "line_no": line_no,
                    "timestamp": parse_timestamp(
                        match.group("date"), match.group("time"), match.group("ampm")
                    ),
                    "rest": match.group("rest"),
                }
            else:
                if current is None:
                    if line.strip():
                        warnings.append(
                            ParseWarning(line_no, "line before first message header, skipped")
                        )
                    continue
                current["rest"] += "\n" + line

    if current is not None:
        messages.append(current)

    return messages, warnings


def classify_message(raw):
    """Split a raw message block into (sender, text) or None if it's a system message."""
    prefix = SENDER + ": "
    if raw["rest"].startswith(prefix):
        return raw["rest"][len(prefix):]
    return None


def build_messages(raw_messages, warnings):
    """Turn raw message blocks into structured authored messages (system messages dropped)."""
    messages = []
    for raw in raw_messages:
        text = classify_message(raw)
        if text is None:
            continue  # system message, not authored by Flavia
        messages.append(
            {
                "line_no": raw["line_no"],
                "timestamp": raw["timestamp"],
                "text": text,
            }
        )
    return messages


def is_valid_note_candidate(message):
    if message is None:
        return False
    if message["text"].strip() == MEDIA_OMITTED:
        return False
    if URL_RE.search(message["text"]):
        return False
    return True


def find_note_before(messages, index, msg_timestamp):
    if index == 0:
        return None
    prev = messages[index - 1]
    if msg_timestamp - prev["timestamp"] > ADJACENCY_WINDOW:
        return None
    if not is_valid_note_candidate(prev):
        return None
    return prev["text"].strip()


def find_note_after(messages, index, msg_timestamp):
    if index == len(messages) - 1:
        return None
    nxt = messages[index + 1]
    if nxt["timestamp"] - msg_timestamp > ADJACENCY_WINDOW:
        return None
    if not is_valid_note_candidate(nxt):
        return None
    return nxt["text"].strip()


def normalize_url(raw_url):
    """Add an https:// scheme to scheme-less www. links; leave others untouched."""
    if raw_url.lower().startswith("www."):
        return "https://" + raw_url
    return raw_url


def extract_records(messages):
    records = []
    next_id = 1

    for index, message in enumerate(messages):
        text = message["text"]
        if text.strip() == MEDIA_OMITTED:
            continue

        urls = list(URL_RE.finditer(text))
        if not urls:
            continue

        before_text = text[: urls[0].start()].strip()
        after_text = text[urls[-1].end() :].strip()

        note_before = before_text or find_note_before(messages, index, message["timestamp"])
        note_after = after_text or find_note_after(messages, index, message["timestamp"])

        for m in urls:
            records.append(
                {
                    "id": next_id,
                    "timestamp": message["timestamp"].isoformat(),
                    "url": normalize_url(m.group(0)),
                    "note_before": note_before,
                    "note_after": note_after,
                    "raw_message": text,
                    "source": SOURCE,
                }
            )
            next_id += 1

    return records


def parse_export(path):
    raw_messages, warnings = read_raw_messages(path)
    messages = build_messages(raw_messages, warnings)
    records = extract_records(messages)
    return records, messages, warnings


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUTPUT

    records, messages, warnings = parse_export(input_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Parsed {len(messages)} authored messages from {input_path}")
    print(f"Found {len(records)} URL records")
    if messages:
        print(f"First message date: {messages[0]['timestamp'].isoformat()}")
        print(f"Last message date: {messages[-1]['timestamp'].isoformat()}")
    print(f"Warnings: {len(warnings)}")
    for w in warnings[:20]:
        print(f"  {w}")
    print(f"Output written to {output_path}")


if __name__ == "__main__":
    main()
