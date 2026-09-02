import json
import os
import sys
from glob import glob

from db import CompanyLocation


def _find_location_shopify_id(external_id):
    """Look up a CompanyLocation's Shopify id from the local DB by external_id."""
    if not external_id:
        return ""
    location = CompanyLocation.select().where(CompanyLocation.external_id == external_id).first()
    return location.shopify_id if location else ""


def _entry_summary(entry):
    return {
        "location_name": entry.get("location_name"),
        "external_id": entry.get("external_id") or "",
        "sap_address_bp_uuid": entry.get("sap_address_bp_uuid") or "",
        "shopify_id": _find_location_shopify_id(entry.get("external_id")),
    }


def main():
    report_path = sys.argv[1] if len(sys.argv) > 1 else sorted(glob("reporte-*.json"))[-1]

    with open(report_path, "r", encoding="utf-8") as f:
        reports = json.load(f)

    no_assignment = []
    one_assignment = []

    for entry in reports:
        count = len(entry.get("final_assignments") or [])
        if count == 0:
            no_assignment.append(_entry_summary(entry))
        elif count == 1:
            one_assignment.append(_entry_summary(entry))

    print(f"Reporte: {report_path}")
    print(f"Total de locations: {len(reports)}")
    print(f"Cuentas sin ninguna asignacion: {len(no_assignment)}")
    print(f"Cuentas con una asignacion: {len(one_assignment)}")

    output = {
        "no_assignment": no_assignment,
        "one_assignment": one_assignment,
    }

    base_name = os.path.splitext(os.path.basename(report_path))[0]
    output_path = f"{base_name}-stats.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Stats guardadas en: {output_path}")


if __name__ == "__main__":
    main()
