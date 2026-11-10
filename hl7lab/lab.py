"""Turn a parsed ORU^R01 message into plain lab-result objects."""

from __future__ import annotations

from dataclasses import dataclass, field

from .flags import Flag, evaluate
from .parser import HL7ParseError, Message


@dataclass
class Patient:
    patient_id: str
    family_name: str
    given_name: str
    dob: str
    sex: str


@dataclass
class Result:
    set_id: str
    value_type: str
    code: str
    name: str
    code_system: str
    value: str
    units: str
    reference_range: str
    sender_flag: str
    status: str
    flag: Flag | None = None

    @property
    def numeric_value(self) -> float | None:
        try:
            return float(self.value)
        except ValueError:
            return None


@dataclass
class Order:
    placer_order_number: str
    filler_order_number: str
    test_code: str
    test_name: str
    observed_at: str
    status: str
    results: list[Result] = field(default_factory=list)


@dataclass
class LabReport:
    control_id: str
    message_type: str
    version: str
    sending_app: str
    sending_facility: str
    message_datetime: str
    patient: Patient
    orders: list[Order]

    @property
    def abnormal_results(self) -> list[tuple[Order, Result]]:
        return [(o, r) for o in self.orders for r in o.results if r.flag and r.flag.is_abnormal]


def to_lab_report(msg: Message) -> LabReport:
    if msg.message_type != "ORU^R01":
        raise HL7ParseError(f"Expected ORU^R01 lab result message, got {msg.message_type}")

    pid = msg.first("PID")
    if pid is None:
        raise HL7ParseError("ORU^R01 message has no PID segment")
    patient = Patient(
        patient_id=pid.get(3, 1),
        family_name=pid.get(5, 1),
        given_name=pid.get(5, 2),
        dob=pid.get(7),
        sex=pid.get(8),
    )
    if not patient.patient_id:
        raise HL7ParseError("PID-3 (patient identifier) is required")

    orders: list[Order] = []
    current: Order | None = None
    for seg in msg.segments:
        if seg.name == "OBR":
            current = Order(
                placer_order_number=seg.get(2),
                filler_order_number=seg.get(3),
                test_code=seg.get(4, 1),
                test_name=seg.get(4, 2),
                observed_at=seg.get(7),
                status=seg.get(25),
            )
            orders.append(current)
        elif seg.name == "OBX":
            if current is None:
                raise HL7ParseError("OBX segment found before any OBR segment")
            result = Result(
                set_id=seg.get(1),
                value_type=seg.get(2),
                code=seg.get(3, 1),
                name=seg.get(3, 2),
                code_system=seg.get(3, 3),
                value=seg.get(5),
                units=seg.get(6, 1),
                reference_range=seg.get(7),
                sender_flag=seg.get(8),
                status=seg.get(11),
            )
            result.flag = evaluate(result.code, result.value, result.reference_range, result.sender_flag)
            current.results.append(result)

    msh = msg.msh
    return LabReport(
        control_id=msg.control_id,
        message_type=msg.message_type,
        version=msg.version,
        sending_app=msh.get(3),
        sending_facility=msh.get(4),
        message_datetime=msh.get(7),
        patient=patient,
        orders=orders,
    )
