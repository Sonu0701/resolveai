from __future__ import annotations
import html, re

SUSPICIOUS_PATTERNS = {
    "instruction_override": r"ignore (all |any )?(previous|prior|system) instructions?",
    "prompt_exfiltration": r"(reveal|show|print).{0,25}(system prompt|hidden prompt|developer message)",
    "policy_bypass": r"(override|bypass) (the )?policy|do not ask for approval",
    "command_execution": r"(execute|run) (this )?(shell|terminal|command)",
}
ORDER_ID_RE = re.compile(r"^NC-\d{6}$")

def sanitize_text(value: str, max_length: int = 5000) -> str:
    """Remove control characters and HTML-escape untrusted display text."""
    clean = re.sub(r"[\x00--]", "", (value or "").strip())
    return html.escape(clean[:max_length], quote=False)

def detect_prompt_injection(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [name for name, pattern in SUSPICIOUS_PATTERNS.items() if re.search(pattern, lowered)]

def validate_order_id(order_id: str | None) -> bool:
    return bool(order_id and ORDER_ID_RE.fullmatch(order_id.strip().upper()))

def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email: return email
    local, domain = email.split("@", 1)
    return f"{local[:1]}{'*' * max(3, len(local)-1)}@{domain}"

def redact_for_log(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+", lambda m: mask_email(m.group(0)) or "", text or "")
    text = re.sub(r"(?i)(api[_ -]?key|token|secret)\s*[:=]\s*\S+", r"=[REDACTED]", text)
    return text[:2000]
