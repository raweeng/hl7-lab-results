"""Command-line interface for the HL7 lab results interface.

Examples:
    python main.py ingest sample_messages/ --db lab.db
    python main.py abnormal --db lab.db
    python main.py fhir sample_messages/02_electrolytes_critical.hl7 --out bundle.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hl7lab import HL7ParseError, parse, split_messages, to_lab_report
from hl7lab.ack import build_ack
from hl7lab.db import abnormal_results, connect, store, summary
from hl7lab.fhir import to_fhir_bundle


def _files(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        out.extend(sorted(p.glob("*.hl7")) if p.is_dir() else [p])
    return out


def cmd_ingest(args: argparse.Namespace) -> int:
    conn = connect(args.db)
    stored = duplicates = errors = 0
    for path in _files(args.paths):
        for raw in split_messages(path.read_text(encoding="utf-8")):
            try:
                msg = parse(raw)
                report = to_lab_report(msg)
            except HL7ParseError as exc:
                errors += 1
                print(f"  ERROR    {path.name}: {exc}")
                continue
            if store(conn, report):
                stored += 1
                n_abn = len(report.abnormal_results)
                print(f"  STORED   {path.name}: {report.control_id} "
                      f"({sum(len(o.results) for o in report.orders)} results, {n_abn} abnormal)")
            else:
                duplicates += 1
                print(f"  SKIPPED  {path.name}: {report.control_id} already received")
            if args.ack:
                print("    ACK -> " + build_ack(msg).replace("\r", " | "))

    s = summary(conn)
    print(f"\nThis run: {stored} stored, {duplicates} duplicates, {errors} rejected")
    print(f"Database: {s['messages']} messages, {s['patients']} patients, "
          f"{s['results']} results, {s['abnormal']} abnormal ({s['critical']} critical)")
    return 1 if errors else 0


def cmd_abnormal(args: argparse.Namespace) -> int:
    rows = abnormal_results(connect(args.db))
    if not rows:
        print("No abnormal results.")
        return 0
    header = f"{'Flag':<5} {'Patient':<22} {'Order':<12} {'Test':<20} {'Result':<18} {'Range':<12} Source"
    print(header)
    print("-" * len(header))
    for r in rows:
        result = f"{r['value']} {r['units']}".strip()
        marker = "!!" if r["flag"] in ("HH", "LL", "AA") else "  "
        print(f"{r['flag']:<3}{marker} {r['patient']:<22} {r['filler_order_number']:<12} "
              f"{r['test_name']:<20} {result:<18} {r['reference_range']:<12} {r['flag_source']}")
    return 0


def cmd_fhir(args: argparse.Namespace) -> int:
    bundles = [to_fhir_bundle(to_lab_report(parse(raw)))
               for raw in split_messages(Path(args.path).read_text(encoding="utf-8"))]
    output = json.dumps(bundles[0] if len(bundles) == 1 else bundles, indent=2)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HL7 v2 lab results interface")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="parse HL7 files and load them into the database")
    p.add_argument("paths", nargs="+", help="HL7 files or folders of .hl7 files")
    p.add_argument("--db", default="lab.db")
    p.add_argument("--ack", action="store_true", help="print the ACK for each message")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("abnormal", help="list abnormal results, critical first")
    p.add_argument("--db", default="lab.db")
    p.set_defaults(func=cmd_abnormal)

    p = sub.add_parser("fhir", help="convert an HL7 file to a FHIR R4 Bundle")
    p.add_argument("path")
    p.add_argument("--out")
    p.set_defaults(func=cmd_fhir)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
