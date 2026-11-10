# HL7 Lab Results Interface

A small Python interface that receives **HL7 v2 lab result messages (ORU^R01)**, stores them in a **SQL database**, **flags abnormal and critical results**, converts them to **FHIR R4** resources and returns **HL7 acknowledgements (ACKs)**.

It models the job a laboratory information system (LIS) interface does every day: take results from an analyser or lab system, check them, store them, and pass them on to the systems clinicians use.

> All patient data in this repository is synthetic. The critical limits are illustrative only and are not clinical guidance.

## What it does

| Feature | Detail |
| --- | --- |
| HL7 v2 parsing | Reads delimiters from MSH-2, handles fields, components, repetitions and escape sequences (`\F\`, `\S\`, `\T\` …), accepts `\r` or `\n` segment endings and strips MLLP framing characters |
| Validation | Rejects messages without MSH, without a control ID (MSH-10), without a patient ID (PID-3), or with OBX before OBR |
| SQL storage | SQLite schema with `messages`, `patients`, `orders` and `results` tables, foreign keys enforced, each message stored in one transaction |
| Duplicate detection | A resent message with the same MSH-10 control ID is skipped, not stored twice |
| Result flagging | 1. Critical limits (HH/LL) → 2. analyser flag in OBX-8 → 3. calculated from the OBX-7 reference range (`3.5-5.2`, `<5.5`, `>60`) |
| FHIR R4 export | Bundle of `Patient`, `DiagnosticReport` and `Observation` resources with LOINC codes, UCUM units, reference ranges and interpretation codes |
| ACK generation | `MSH` + `MSA|AA|<control id>` returned to the sending system |
| Tests | 21 automated unit tests covering parsing, flagging, storage, FHIR and ACKs |

No external packages: Python 3.10+ standard library only.

## Quick start

```bash
git clone https://github.com/raweeng/hl7-lab-results.git
cd hl7-lab-results

python main.py ingest sample_messages --ack     # parse and load into lab.db
python main.py abnormal                          # list abnormal results, critical first
python main.py fhir sample_messages/02_electrolytes_critical.hl7 --out bundle.json

python -m unittest discover -s tests -t .        # run the tests
```

## Example output

```
$ python main.py ingest sample_messages
  STORED   01_full_blood_count.hl7: MSG00001 (3 results, 2 abnormal)
  STORED   02_electrolytes_critical.hl7: MSG00002 (4 results, 3 abnormal)
  STORED   03_glucose_no_sender_flags.hl7: MSG00003 (4 results, 2 abnormal)
  SKIPPED  04_resent_duplicate.hl7: MSG00001 already received

This run: 3 stored, 1 duplicates, 0 rejected
Database: 3 messages, 3 patients, 11 results, 7 abnormal (2 critical)

$ python main.py abnormal
Flag  Patient                Order        Test                 Result             Range        Source
-----------------------------------------------------------------------------------------------------
HH !! SAMPLE, JORDAN         LAB5002      Potassium            6.8 mmol/L         3.5-5.2      critical-limit
LL !! DEMO, CASEY            LAB5003      Glucose              2.1 mmol/L         3.0-5.4      critical-limit
L     TESTPATIENT, ALEX      LAB5001      Haemoglobin          118 g/L            130-180      sender
H     TESTPATIENT, ALEX      LAB5001      White cell count     12.4 10*9/L        4.0-11.0     sender
H     SAMPLE, JORDAN         LAB5002      Creatinine           145 umol/L         60-110       sender
L     SAMPLE, JORDAN         LAB5002      eGFR                 42 mL/min/1.73m2   >60          reference-range
H     DEMO, CASEY            LAB5004      Triglycerides        2.6 mmol/L         <2.0         reference-range
```

A full FHIR bundle produced from message 02 is in [`example_fhir_bundle.json`](example_fhir_bundle.json).

## How an ORU^R01 message maps to the database

```
MSH  → messages   (sending app/facility, MSH-7 time, MSH-10 control ID, MSH-12 version)
PID  → patients   (PID-3 ID, PID-5 name, PID-7 DOB, PID-8 sex)
OBR  → orders     (OBR-2/3 order numbers, OBR-4 test panel, OBR-7 collected, OBR-25 status)
OBX  → results    (OBX-3 LOINC code, OBX-5 value, OBX-6 units, OBX-7 range, OBX-8 flag, OBX-11 status)
```

`queries.sql` has example SQL for interface monitoring and data extracts: critical results, abnormal rate per test, messages per sending system and a patient's result history.

## Project structure

```
hl7lab/
  parser.py   HL7 v2 parsing (delimiters, components, escapes, validation)
  lab.py      ORU^R01 → Patient / Order / Result objects
  flags.py    abnormal and critical result flagging
  db.py       SQL schema, transactional storage, duplicate detection, queries
  fhir.py     FHIR R4 Bundle conversion
  ack.py      HL7 ACK messages
main.py       command-line interface
sample_messages/  synthetic ORU^R01 messages
tests/        unit tests
queries.sql   example SQL
```

## Design notes

- **Why read delimiters from MSH?** HL7 allows senders to choose their own encoding characters, so a parser that hard-codes `|` and `^` can break on a valid message.
- **Why keep the source of each flag?** In a lab, it matters whether "H" came from the analyser, from a reference range or from a critical-value rule. Critical values usually trigger a phone call to the clinician, so they are sorted to the top.
- **Why duplicate detection?** Interface engines resend messages after timeouts. Using MSH-10 keeps a resend from creating duplicate results.

## Not included (next steps)

- An MLLP TCP listener, so it can receive messages live rather than from files
- Other message types (ADT for patient admissions, ORM/OML for orders)
- Replacing SQLite with Oracle or SQL Server, and a production-grade FHIR validator
