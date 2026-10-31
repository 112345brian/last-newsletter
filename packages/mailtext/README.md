# mailtext

Two small things almost anything that reads parsed email ends up needing:

```python
import email
from mailtext import decode_header_value, extract_body_text

msg = email.message_from_bytes(raw_bytes)
subject = decode_header_value(msg.get("Subject"))  # joins RFC 2047 encoded-words into one string
body = extract_body_text(msg)  # text/plain if present, else text/html -> text
```

No IMAP, no POP, no app-specific concept anywhere in it — just header decoding
and body extraction over a stdlib `email.message.Message`. `extract_body_text`
falls back to `html2text` only when there's no `text/plain` part at all.
