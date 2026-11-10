import json
import sqlite3
import unittest
from pathlib import Path

from hl7lab import HL7ParseError, parse, split_messages, to_lab_report
from hl7lab.ack import build_ack
from hl7lab.db import abnormal_results, connect, store, summary
from hl7lab.fhir import hl7_datetime, to_fhir_bundle
from hl7lab.flags import evaluate, parse_range

SAMPLES = Path(__file__).resolve().parent.parent / "sample_messages"


def load(name: str):
    return parse((SAMPLES / name).read_text())


class ParserTests(unittest.TestCase):
    def test_msh_fields_are_aligned_with_the_standard(self):
        msg = load("01_full_blood_count.hl7")
        self.assertEqual(msg.msh.get(1), "|")
        self.assertEqual(msg.msh.get(3), "LABANALYSER")
        self.assertEqual(msg.message_type, "ORU^R01")
        self.assertEqual(msg.control_id, "MSG00001")
        self.assertEqual(msg.version, "2.6")

    def test_components(self):
        pid = load("01_full_blood_count.hl7").first("PID")
        self.assertEqual(pid.get(3, 1), "MRN100001")
        self.assertEqual(pid.get(5, 2), "ALEX")

    def test_escape_sequences_are_decoded(self):
        report = to_lab_report(load("03_glucose_no_sender_flags.hl7"))
        comment = report.orders[1].results[-1]
        self.assertEqual(comment.value, "Fasting sample & collected 07:30")

    def test_accepts_newline_segment_endings(self):
        text = (SAMPLES / "01_full_blood_count.hl7").read_text().replace("\r", "\n")
        self.assertEqual(len(parse(text).all("OBX")), 3)

    def test_rejects_message_without_msh(self):
        with self.assertRaises(HL7ParseError):
            parse("PID|1||123")

    def test_rejects_message_without_control_id(self):
        with self.assertRaises(HL7ParseError):
            parse("MSH|^~\\&|A|B|C|D|20261109||ORU^R01||P|2.6")

    def test_rejects_obx_before_obr(self):
        msg = parse("MSH|^~\\&|A|B|C|D|20261109||ORU^R01|X1|P|2.6\rPID|1||P1\rOBX|1|NM|1^A^LN||5")
        with self.assertRaises(HL7ParseError):
            to_lab_report(msg)

    def test_split_messages(self):
        a = (SAMPLES / "01_full_blood_count.hl7").read_text()
        b = (SAMPLES / "02_electrolytes_critical.hl7").read_text()
        self.assertEqual(len(split_messages(a + b)), 2)


class FlagTests(unittest.TestCase):
    def test_parse_range(self):
        self.assertEqual(parse_range("3.5-5.2"), (3.5, 5.2))
        self.assertEqual(parse_range("<5.5"), (None, 5.5))
        self.assertEqual(parse_range(">60"), (60.0, None))
        self.assertIsNone(parse_range("see comment"))

    def test_critical_limit_overrides_sender_flag(self):
        flag = evaluate("2823-3", "6.8", "3.5-5.2", "H")
        self.assertEqual((flag.code, flag.source), ("HH", "critical-limit"))
        self.assertTrue(flag.is_critical)

    def test_sender_flag_used_when_present(self):
        flag = evaluate("6690-2", "12.4", "4.0-11.0", "H")
        self.assertEqual((flag.code, flag.source), ("H", "sender"))

    def test_flag_calculated_from_range_when_sender_sends_none(self):
        flag = evaluate("2571-8", "2.6", "<2.0", "")
        self.assertEqual((flag.code, flag.source), ("H", "reference-range"))

    def test_normal_result(self):
        self.assertFalse(evaluate("2951-2", "138", "135-145", "N").is_abnormal)

    def test_text_result_is_not_flagged(self):
        self.assertEqual(evaluate("8251-1", "Haemolysed", "", "").code, "N")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")

    def test_store_and_query_abnormal(self):
        for name in ("01_full_blood_count.hl7", "02_electrolytes_critical.hl7"):
            self.assertTrue(store(self.conn, to_lab_report(load(name))))
        rows = abnormal_results(self.conn)
        self.assertEqual(rows[0]["flag"], "HH")  # critical results come first
        self.assertEqual(rows[0]["test_name"], "Potassium")
        self.assertEqual(summary(self.conn)["critical"], 1)

    def test_duplicate_message_is_not_stored_twice(self):
        report = to_lab_report(load("01_full_blood_count.hl7"))
        self.assertTrue(store(self.conn, report))
        self.assertFalse(store(self.conn, report))
        self.assertEqual(summary(self.conn)["results"], 3)

    def test_foreign_keys_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO results (order_id, flag, flag_source) VALUES (999, 'N', 'x')")


class FhirTests(unittest.TestCase):
    def test_bundle_structure(self):
        bundle = to_fhir_bundle(to_lab_report(load("02_electrolytes_critical.hl7")))
        types = [e["resource"]["resourceType"] for e in bundle["entry"]]
        self.assertEqual(types, ["Patient", "DiagnosticReport"] + ["Observation"] * 4)
        json.dumps(bundle)  # must be valid JSON

    def test_observation_content(self):
        bundle = to_fhir_bundle(to_lab_report(load("02_electrolytes_critical.hl7")))
        potassium = bundle["entry"][3]["resource"]
        self.assertEqual(potassium["code"]["coding"][0],
                         {"system": "http://loinc.org", "code": "2823-3", "display": "Potassium"})
        self.assertEqual(potassium["valueQuantity"]["value"], 6.8)
        self.assertEqual(potassium["interpretation"][0]["coding"][0]["code"], "HH")
        self.assertEqual(potassium["referenceRange"][0]["high"]["value"], 5.2)
        self.assertEqual(potassium["status"], "final")

    def test_datetime_conversion(self):
        self.assertEqual(hl7_datetime("20261109083000"), "2026-11-09T08:30:00+08:00")
        self.assertEqual(hl7_datetime("19850214"), "1985-02-14")


class AckTests(unittest.TestCase):
    def test_ack_references_original_message(self):
        ack = build_ack(load("01_full_blood_count.hl7"))
        msh, msa = ack.split("\r")
        self.assertIn("ACK^R01", msh)
        self.assertTrue(msh.split("|")[4] == "LABANALYSER")  # sent back to the sender
        self.assertEqual(msa, "MSA|AA|MSG00001")


if __name__ == "__main__":
    unittest.main()
