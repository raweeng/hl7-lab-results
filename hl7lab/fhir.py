"""Convert a lab report into a FHIR R4 Bundle (Patient, DiagnosticReport, Observations)."""

from __future__ import annotations

import re

from .flags import parse_range
from .lab import LabReport, Result

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
INTERPRETATION = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
DEFAULT_TZ = "+08:00"  # HL7 timestamps here carry no offset; assume Perth (AWST)

STATUS = {"F": "final", "P": "preliminary", "C": "corrected", "X": "cancelled", "R": "registered"}
SEX = {"M": "male", "F": "female", "O": "other", "U": "unknown"}


def hl7_datetime(ts: str) -> str | None:
    """'20261109083000' -> '2026-11-09T08:30:00+08:00'; '19850214' -> '1985-02-14'."""
    m = re.match(r"^(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", ts or "")
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    if not h:
        return "-".join(p for p in (y, mo, d) if p)
    return f"{y}-{mo}-{d}T{h}:{mi or '00'}:{s or '00'}{DEFAULT_TZ}"


def _safe_id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9\-.]", "-", text)[:64]


def _observation(report: LabReport, order_key: str, r: Result, effective: str | None) -> dict:
    obs: dict = {
        "resourceType": "Observation",
        "id": _safe_id(f"{order_key}-{r.set_id}"),
        "status": STATUS.get(r.status, "unknown"),
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "laboratory",
            }]
        }],
        "code": {
            "coding": [{"system": LOINC if r.code_system == "LN" else r.code_system,
                        "code": r.code, "display": r.name}],
            "text": r.name,
        },
        "subject": {"reference": f"Patient/{_safe_id(report.patient.patient_id)}"},
    }
    if effective:
        obs["effectiveDateTime"] = effective

    if r.numeric_value is not None:
        obs["valueQuantity"] = {"value": r.numeric_value, "unit": r.units,
                                "system": UCUM, "code": r.units}
    else:
        obs["valueString"] = r.value

    if rng := parse_range(r.reference_range):
        ref: dict = {"text": r.reference_range}
        if rng[0] is not None:
            ref["low"] = {"value": rng[0], "unit": r.units}
        if rng[1] is not None:
            ref["high"] = {"value": rng[1], "unit": r.units}
        obs["referenceRange"] = [ref]

    if r.flag:
        obs["interpretation"] = [{
            "coding": [{"system": INTERPRETATION, "code": r.flag.code, "display": r.flag.label}]
        }]
    return obs


def to_fhir_bundle(report: LabReport) -> dict:
    p = report.patient
    patient_id = _safe_id(p.patient_id)
    entries: list[dict] = [{
        "resource": {
            "resourceType": "Patient",
            "id": patient_id,
            "identifier": [{"value": p.patient_id}],
            "name": [{"family": p.family_name, "given": [p.given_name]}],
            "gender": SEX.get(p.sex, "unknown"),
            "birthDate": hl7_datetime(p.dob),
        }
    }]

    for order in report.orders:
        order_key = order.filler_order_number or order.placer_order_number or report.control_id
        effective = hl7_datetime(order.observed_at)
        observations = [_observation(report, order_key, r, effective) for r in order.results]
        entries.append({
            "resource": {
                "resourceType": "DiagnosticReport",
                "id": _safe_id(order_key),
                "status": STATUS.get(order.status, "unknown"),
                "code": {"coding": [{"code": order.test_code, "display": order.test_name}],
                         "text": order.test_name},
                "subject": {"reference": f"Patient/{patient_id}"},
                "effectiveDateTime": effective,
                "result": [{"reference": f"Observation/{o['id']}"} for o in observations],
            }
        })
        entries.extend({"resource": o} for o in observations)

    return {"resourceType": "Bundle", "type": "collection", "entry": entries}
