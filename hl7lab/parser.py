"""Minimal HL7 v2.x parser (standard library only).

Handles the parts of HL7 v2 needed for lab result messages (ORU^R01):
segments, fields, repetitions, components and escape sequences.
Delimiters are read from the MSH segment rather than hard-coded.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class HL7ParseError(ValueError):
    """Raised when a message is not valid HL7 v2."""


@dataclass(frozen=True)
class Delimiters:
    field: str = "|"
    component: str = "^"
    repetition: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"


def unescape(value: str, d: Delimiters) -> str:
    """Convert HL7 escape sequences (e.g. \\F\\ -> |) back to plain text."""
    if d.escape not in value:
        return value
    e = d.escape
    replacements = {
        f"{e}F{e}": d.field,
        f"{e}S{e}": d.component,
        f"{e}R{e}": d.repetition,
        f"{e}T{e}": d.subcomponent,
        f"{e}E{e}": d.escape,
        f"{e}.br{e}": "\n",
    }
    for seq, char in replacements.items():
        value = value.replace(seq, char)
    return value


@dataclass
class Segment:
    """One HL7 segment. fields[n] is field n (fields[0] is the segment name)."""

    name: str
    fields: list[str]
    delimiters: Delimiters

    def get(self, n: int, component: int = 1, repetition: int = 1) -> str:
        """Return field n, component (1-based), repetition (1-based) as text."""
        if n >= len(self.fields):
            return ""
        raw = self.fields[n]
        if self.name == "MSH" and n in (1, 2):
            return raw  # delimiters themselves, never split
        reps = raw.split(self.delimiters.repetition)
        if repetition > len(reps):
            return ""
        comps = reps[repetition - 1].split(self.delimiters.component)
        if component > len(comps):
            return ""
        return unescape(comps[component - 1], self.delimiters)

    def raw(self, n: int) -> str:
        return self.fields[n] if n < len(self.fields) else ""


@dataclass
class Message:
    segments: list[Segment] = field(default_factory=list)
    delimiters: Delimiters = field(default_factory=Delimiters)

    def first(self, name: str) -> Segment | None:
        return next((s for s in self.segments if s.name == name), None)

    def all(self, name: str) -> list[Segment]:
        return [s for s in self.segments if s.name == name]

    @property
    def msh(self) -> Segment:
        seg = self.first("MSH")
        assert seg is not None
        return seg

    @property
    def message_type(self) -> str:
        """e.g. 'ORU^R01'."""
        return f"{self.msh.get(9, 1)}^{self.msh.get(9, 2)}"

    @property
    def control_id(self) -> str:
        return self.msh.get(10)

    @property
    def version(self) -> str:
        return self.msh.get(12)


def parse(text: str) -> Message:
    """Parse one HL7 v2 message. Accepts \\r, \\n or \\r\\n segment endings."""
    text = text.strip().lstrip("﻿")
    # MLLP framing characters, in case a captured message still has them
    text = text.strip("\x0b\x1c")
    if not text.startswith("MSH"):
        raise HL7ParseError("Message must start with an MSH segment")
    if len(text) < 8:
        raise HL7ParseError("MSH segment too short to hold delimiters")

    field_sep = text[3]
    enc = text[4:8]
    if len(set(enc)) != 4 or field_sep in enc:
        raise HL7ParseError(f"Invalid encoding characters in MSH-2: {enc!r}")
    d = Delimiters(field_sep, enc[0], enc[1], enc[2], enc[3])

    lines = [ln for ln in text.replace("\r\n", "\r").replace("\n", "\r").split("\r") if ln.strip()]
    msg = Message(delimiters=d)
    for line in lines:
        parts = line.split(field_sep)
        name = parts[0]
        if len(name) != 3 or not name.isalnum():
            raise HL7ParseError(f"Invalid segment name: {name!r}")
        if name == "MSH":
            # MSH-1 is the field separator itself, so re-insert it to keep
            # field numbers aligned with the HL7 standard.
            parts = ["MSH", field_sep] + parts[1:]
        msg.segments.append(Segment(name, parts, d))

    if not msg.control_id:
        raise HL7ParseError("MSH-10 (message control ID) is required")
    return msg


def split_messages(text: str) -> list[str]:
    """Split a file that may contain several messages, each starting with MSH."""
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    chunks, current = [], []
    for line in text.split("\r"):
        if line.startswith("MSH") and current:
            chunks.append("\r".join(current))
            current = []
        if line.strip():
            current.append(line)
    if current:
        chunks.append("\r".join(current))
    return chunks
