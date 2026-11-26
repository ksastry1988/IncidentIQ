"""Redaction of sensitive data from everything a tool returns.

Secrets configured for the server (`INCIDENTIQ_TOOL_REDACT_VALUES`) are masked
wherever they appear; common credential shapes are masked heuristically.
"""
import re
from typing import Any, Iterable

from app.config import ToolRedactionSettings

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"pass(word|wd|phrase)?|secret|token|api[-_ ]?key|apikey|(?<![a-z])auth(?:orization)?(?![a-z])|credential|"
    r"private[-_ ]?key|access[-_ ]?key|session[-_ ]?id|cookie|connection[-_ ]?string|"
    r"conn[-_ ]?str|dsn|signature|bearer|\bpwd\b",
    re.IGNORECASE,
)
_KEY = r"[\w.-]*(?:pass(?:word|wd|phrase)?|pwd|secret|token|api[-_]?key|apikey|auth(?:orization)?|credentials?|private[-_]?key|access[-_]?key|cookie|signature)[\w.-]*"

# (pattern, replacement); replacement keeps non-secret context such as the key name.
_TEXT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S), REDACTED),
    # Authorization / Cookie style headers: mask the rest of the line.
    (re.compile(r"(?i)\b((?:proxy-)?authorization|set-cookie|cookie|x-api-key)(\s*[:=]\s*)[^\r\n]+"), rf"\1\2{REDACTED}"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}"), rf"\1 {REDACTED}"),
    # scheme://user:password@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]*:)[^\s@/]+(@)"), rf"\1{REDACTED}\2"),
    # key=value / key: value / "key": "value" for sensitive key names
    (re.compile(rf"""(?i)(["']?{_KEY}["']?\s*[:=]\s*)(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s,;&"'}}\]]+)"""), rf"\1{REDACTED}"),
    # connection-string segments: Password=...; Pwd=...; AccountKey=...
    (re.compile(r"(?i)\b((?:password|pwd|accountkey|sharedaccesskey)\s*=\s*)[^;\s]+"), rf"\1{REDACTED}"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), REDACTED),  # JWT
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), REDACTED),  # AWS key id
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|sk-[A-Za-z0-9_-]{16,}|xox[abprs]-[A-Za-z0-9-]{10,})"), REDACTED),
]


class Redactor:
    """Masks secrets in strings and, recursively, in dicts, lists, and tuples.

    `redactions` counts replacements made by the last `redact` call.
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        # Longest first so a secret containing another is masked whole.
        values = sorted({s for s in secrets if s}, key=len, reverse=True)
        self._secrets = values
        self._count = 0

    @classmethod
    def from_settings(cls, settings: ToolRedactionSettings | None = None) -> "Redactor":
        settings = settings or ToolRedactionSettings()
        return cls(v.strip() for v in settings.tool_redact_values.split(","))

    def redact(self, value: Any, preserve: Iterable[str] = ()) -> tuple[Any, int]:
        """Return a redacted copy of `value` and the number of replacements.

        Top-level dict keys named in `preserve` keep their values untouched (for
        fixed protocol fields that a configured secret must not corrupt).
        """
        keep = frozenset(preserve)
        count = 0

        def text(s: str) -> str:
            nonlocal count
            for secret in self._secrets:
                if secret in s:
                    count += s.count(secret)
                    s = s.replace(secret, REDACTED)
            for pattern, repl in _TEXT_RULES:
                s, n = pattern.subn(repl, s)
                count += n
            return s

        def walk(v: Any, top: bool = False) -> Any:
            nonlocal count
            if isinstance(v, str):
                return text(v)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if str(v) in self._secrets:
                    count += 1
                    return REDACTED
                return v
            if isinstance(v, dict):
                out: dict[Any, Any] = {}
                for k, item in v.items():
                    if top and k in keep:
                        out[k] = item
                        continue
                    key = text(k) if isinstance(k, str) else k
                    if (
                        isinstance(k, str)
                        and _SENSITIVE_KEY.search(k)
                        and item is not None
                        and item != REDACTED
                        and not isinstance(item, bool)
                    ):
                        count += 1
                        out[key] = REDACTED
                    else:
                        out[key] = walk(item)
                return out
            if isinstance(v, (list, tuple)):
                return [walk(i) for i in v]
            return v

        return walk(value, True), count
