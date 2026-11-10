"""Build HL7 v2 acknowledgement (ACK) messages.

A receiving system sends an ACK back for every message:
AA = accepted, AE = application error, AR = rejected.
"""

from __future__ import annotations

from datetime import datetime

from .parser import Message

RECEIVING_APP = "HL7LAB"
RECEIVING_FACILITY = "DEMO"


def build_ack(msg: Message, code: str = "AA", error: str = "") -> str:
    msh = msg.msh
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    trigger = msh.get(9, 2)
    segments = [
        "|".join([
            "MSH", "^~\\&", RECEIVING_APP, RECEIVING_FACILITY,
            msh.get(3), msh.get(4),  # reply goes back to the original sender
            now, "", f"ACK^{trigger}", f"ACK{msg.control_id}", "P", msg.version or "2.6",
        ]),
        "|".join(["MSA", code, msg.control_id] + ([error] if error else [])),
    ]
    return "\r".join(segments)
