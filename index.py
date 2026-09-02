
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from dotenv import load_dotenv

#Env Configuration, SAP keys and Shopify Endpoints. Get from the .env file
load_dotenv()

SAP_BASE_URL = os.getenv("SAP_BASE_URL")
SAP_USERNAME = os.getenv("SAP_USERNAME")
SAP_PASSWORD = os.getenv("SAP_PASSWORD")

SHOPIFY_STORE_URL = os.getenv("SHOPIFY_STORE_URL")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")

#First, we are going to batch all companies and company locations in two tables in sqlite, companies and companies locations.
#Only matters the SAP Id metafield., the external id and the shopify id.

from db import db, Company, CompanyLocation, StaffAccount, StaffAssignment, SapBpAddress, SapAddress
from shopify import (
    paginate_companies,
    get_companies_by_ids,
    paginate_company_locations,
    company_location_assign_staff_members,
    remove_staff_from_location,
)
from sap import fetch_bp_addresses_page, BP_ADDRESS_FIELD_MAP, fetch_addresses_page, ADDRESS_FIELD_MAP, PAGE_SIZE

# Restrict batch_companies_and_locations() to these Shopify company ids
# for testing (bare numeric id or full gid://shopify/Company/... both
# work). Leave empty/None to process every company.
test_list = [
    'gid://shopify/Company/30058971214',
    'gid://shopify/Company/10949591118',
    'gid://shopify/Company/10949296206',
    'gid://shopify/Company/10710319182',
    'gid://shopify/Company/10949886030',
    'gid://shopify/Company/10771136590',
    'gid://shopify/Company/10949787726',

]

STAFF_NAME_EQUIVALENCES = {
    "jenmcsween": "jennifermcsween",
}

def _to_company_gid(item):
    """Normalize a test_list entry (bare numeric id or full gid) to the
    full gid://shopify/Company/... form the Shopify API expects."""
    item = str(item)
    return item if item.startswith("gid://") else f"gid://shopify/Company/{item}"


def _save_company(company_node):
    """Create a Company record from a Shopify company node."""
    company_shopify_id = company_node.get("id") or ""
    company_name = company_node.get("name") or ""
    company_external_id = company_node.get("externalId") or ""
    company_sap_id = ""

    metafield = company_node.get("metafield")
    if metafield:
        company_sap_id = metafield.get("value") or ""

    return Company.create(
        shopify_id=company_shopify_id,
        sap_id=company_sap_id,
        external_id=company_external_id,
        name=company_name,
    )


def _build_location_records(company, location_nodes):
    """
    Build a list of CompanyLocation model instances for bulk insert, plus a
    map of location shopify_id -> its staffMemberAssignments nodes so staff
    can be linked once the locations have been saved and have local ids.
    """
    locations = []
    staff_assignments_by_location = {}
    for location_node in location_nodes:
        location_metafield = location_node.get("metafield")
        location_sap_id = ""
        if location_metafield:
            location_sap_id = location_metafield.get("value") or ""

        location_shopify_id = location_node.get("id") or ""

        locations.append(
            CompanyLocation(
                company=company,
                company_shopify_id=company.shopify_id,
                shopify_id=location_shopify_id,
                sap_id=location_sap_id,
                external_id=location_node.get("externalId") or "",
                name=location_node.get("name") or "",
            )
        )

        assignment_nodes = (location_node.get("staffMemberAssignments") or {}).get("nodes") or []
        if assignment_nodes:
            staff_assignments_by_location[location_shopify_id] = assignment_nodes

    return locations, staff_assignments_by_location




def _apply_sap_equivalence(normalized_name):
    """
    Apply SAP staff name equivalences to normalize Shopify names to SAP format.
    For example: jenmcsween -> jennifermcsween (use full name as in SAP)
    """
    if not normalized_name:
        return normalized_name
    return STAFF_NAME_EQUIVALENCES.get(normalized_name, normalized_name)

def _get_or_create_staff_account(staff_member):
    """Get or create a StaffAccount from a Shopify staffMember node,
    keeping its name/email/normalized_name in sync on subsequent runs."""
    staff_shopify_id = staff_member.get("id") or ""
    email = staff_member.get("email") or ""
    first_name = staff_member.get("firstName") or ""
    last_name = staff_member.get("lastName") or ""
    normalized_name = _normalize_rep_name(f"{first_name} {last_name}".strip())
    normalized_name = _apply_sap_equivalence(normalized_name)

    staff_account, created = StaffAccount.get_or_create(
        shopify_id=staff_shopify_id,
        defaults={
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "normalized_name": normalized_name,
        },
    )

    if not created and (
        staff_account.email != email
        or staff_account.first_name != first_name
        or staff_account.last_name != last_name
        or staff_account.normalized_name != normalized_name
    ):
        staff_account.email = email
        staff_account.first_name = first_name
        staff_account.last_name = last_name
        staff_account.normalized_name = normalized_name
        staff_account.save()

    return staff_account


def _save_staff_assignments(company, staff_assignments_by_location):
    """
    Given the just-inserted locations for a company and a map of
    location shopify_id -> staffMemberAssignments nodes, resolve each
    location's local id and save the StaffAccount/StaffAssignment records.
    """
    if not staff_assignments_by_location:
        return 0

    saved_locations = CompanyLocation.select().where(
        (CompanyLocation.company == company)
        & (CompanyLocation.shopify_id.in_(list(staff_assignments_by_location.keys())))
    )

    assignment_records = []
    for location in saved_locations:
        for assignment_node in staff_assignments_by_location[location.shopify_id]:
            staff_member = assignment_node.get("staffMember") or {}
            staff_account = _get_or_create_staff_account(staff_member)
            assignment_records.append(
                StaffAssignment(
                    company_location=location,
                    staff_account=staff_account,
                    shopify_id=assignment_node.get("id") or "",
                )
            )

    if assignment_records:
        with db.atomic():
            StaffAssignment.bulk_create(assignment_records, batch_size=100)

    return len(assignment_records)


def batch_companies_and_locations():
    """
    Fetch all companies and company locations from Shopify and save them
    to the local SQLite database using peewee models.
    Company locations are fetched in parallel using 15 threads to speed up
    the process, since some companies have up to 2000 locations.
    """
    print("Starting batch of companies and company locations...")

    # Clean existing data in correct order due to foreign key constraint
    StaffAssignment.delete().execute()
    CompanyLocation.delete().execute()
    Company.delete().execute()
    print("Cleared existing company, company location and staff assignment data")

    # Fetch companies from Shopify - a direct lookup for just the
    # test_list ids when set, otherwise every company
    if test_list:
        companies = get_companies_by_ids([_to_company_gid(item) for item in test_list])
        print(f"test_list active: fetched {len(companies)} companies directly by id")
    else:
        companies = paginate_companies()
        print(f"Fetched {len(companies)} companies from Shopify")

    # Save companies to the database and build a lookup map
    company_map = {}
    with db.atomic():
        for company_node in companies:
            company = _save_company(company_node)
            company_map[company.shopify_id] = company

    print(f"Fetching locations for {len(companies)} companies using 15 threads...")

    total_locations = 0
    total_staff_assignments = 0
    processed_count = 0

    # Fetch company locations (with their staff assignments) in parallel using 15 threads
    with ThreadPoolExecutor(15) as executor:
        future_to_company_id = {
            executor.submit(paginate_company_locations, company_id): company_id
            for company_id in company_map.keys()
        }

        for future in as_completed(future_to_company_id):
            company_id = future_to_company_id[future]
            company = company_map[company_id]

            try:
                location_nodes = future.result()
            except Exception as exc:
                print(f"Error fetching locations for company {company.name}: {exc}")
                continue

            processed_count += 1
            total_locations += len(location_nodes)

            staff_count = 0
            if location_nodes:
                locations, staff_assignments_by_location = _build_location_records(company, location_nodes)
                with db.atomic():
                    CompanyLocation.bulk_create(locations, batch_size=100)

                staff_count = _save_staff_assignments(company, staff_assignments_by_location)
                total_staff_assignments += staff_count

            print(f"  [{processed_count}/{len(companies)}] {company.name}: {len(location_nodes)} locations, {staff_count} staff assigned")

    print(f"Total locations saved: {total_locations}")
    print(f"Total staff assignments saved: {total_staff_assignments}")
    print("Batch completed successfully")


def batch_sap_bp_addresses():
    """
    Fetch every row from the SAP ByDesign RPBUPCSD_Q0001QueryResults
    analytics query and save them as-is to the SapBpAddress table, one
    fetched page at a time instead of holding the full result set in memory.
    """
    print("Starting batch of SAP business partner addresses...")

    SapBpAddress.delete().execute()
    print("Cleared existing SAP business partner address data")

    total_saved = 0
    page_num = 0
    skip = 0

    while True:
        rows = fetch_bp_addresses_page(skip)
        page_num += 1
        print(f"SAP BP addresses: page {page_num}, retrieved {len(rows)}")

        records = [
            SapBpAddress(
                **{
                    friendly_name: row.get(technical_name) or ""
                    for technical_name, friendly_name in BP_ADDRESS_FIELD_MAP.items()
                }
            )
            for row in rows
        ]
        if records:
            with db.atomic():
                SapBpAddress.bulk_create(records, batch_size=100)
            total_saved += len(records)

        if len(rows) < PAGE_SIZE:
            break
        skip += PAGE_SIZE

    print(f"Total SAP business partner address rows saved: {total_saved}")
    print("Batch completed successfully")


def batch_sap_addresses():
    """
    Fetch every row from the SAP ByDesign RPZ354E43506089F046ADF360QueryResults
    analytics query and save them as-is to the SapAddress table, one
    fetched page at a time instead of holding the full result set in memory.
    """
    print("Starting batch of SAP addresses...")

    SapAddress.delete().execute()
    print("Cleared existing SAP address data")

    total_saved = 0
    page_num = 0
    skip = 0

    while True:
        rows = fetch_addresses_page(skip)
        page_num += 1
        print(f"SAP addresses: page {page_num}, retrieved {len(rows)}")

        records = [
            SapAddress(
                **{
                    friendly_name: row.get(technical_name) or ""
                    for technical_name, friendly_name in ADDRESS_FIELD_MAP.items()
                }
            )
            for row in rows
        ]
        if records:
            with db.atomic():
                SapAddress.bulk_create(records, batch_size=100)
            total_saved += len(records)

        if len(rows) < PAGE_SIZE:
            break
        skip += PAGE_SIZE

    print(f"Total SAP address rows saved: {total_saved}")
    print("Batch completed successfully")

def _normalize_rep_name(value):
    """
    Normalize a SAP rep name for matching: lowercase, spaces removed.
    Returns None (not a string) for "not assigned" or empty values, so a
    missing rep never masquerades as a name.
    """
    if not value:
        return None

    normalized = value.strip().lower().replace(" ", "")
    if not normalized or normalized == "notassigned":
        return None

    return normalized


def normalize_sap_address_reps():
    """
    Normalize rep names and address_uuid in SapAddress records and sync them from matching
    SapBpAddress records using bp_uuid (SapAddress) and account_id (SapBpAddress).
    Processes in batches to avoid memory overload.
    """
    print("Starting normalization and sync of SAP address rep names...")

    bp_addresses = list(SapBpAddress.select())
    bp_address_by_account_id = {bp.account_id: bp for bp in bp_addresses}
    
    total_addresses = SapAddress.select().count()
    processed_count = 0
    batch_size = PAGE_SIZE

    while processed_count < total_addresses:
        addresses = list(
            SapAddress.select()
            .limit(batch_size)
            .offset(processed_count)
        )
        
        if not addresses:
            break

        for address in addresses:
            bp_address = bp_address_by_account_id.get(address.bp_uuid)
            
            if bp_address:
                address.corporate_rep_normalized = bp_address.corporate_rep_normalized
                address.inside_sales_rep_normalized = bp_address.inside_sales_rep_normalized
                address.outside_sales_rep_normalized = bp_address.outside_sales_rep_normalized
            else:
                address.corporate_rep_normalized = None
                address.inside_sales_rep_normalized = None
                address.outside_sales_rep_normalized = None
            
            if address.address_uuid:
                normalized = address.address_uuid.lower().replace(" ", "").replace("_", "").replace("-", "")
                address.norm_address_uuid = normalized if normalized else None
            else:
                address.norm_address_uuid = None

        with db.atomic():
            SapAddress.bulk_update(
                addresses,
                fields=[
                    SapAddress.corporate_rep_normalized,
                    SapAddress.inside_sales_rep_normalized,
                    SapAddress.outside_sales_rep_normalized,
                    SapAddress.norm_address_uuid,
                ],
                batch_size=100,
            )

        processed_count += len(addresses)
        print(f"  Processed {processed_count}/{total_addresses} SAP address rows")

    print(f"Normalized and synced rep names for {total_addresses} SAP address rows")


def normalize_sap_bp_address_reps():
    """
    Populate the normalized outside/inside/corporate rep columns on every
    SapBpAddress row from their corresponding _text columns, in batches.
    """
    print("Starting normalization of SAP BP address rep names...")

    addresses = list(SapBpAddress.select())
    for address in addresses:
        address.outside_sales_rep_normalized = _normalize_rep_name(address.outside_sales_rep_text)
        address.inside_sales_rep_normalized = _normalize_rep_name(address.inside_sales_rep_text)
        address.corporate_rep_normalized = _normalize_rep_name(address.corporate_rep_text)

    with db.atomic():
        SapBpAddress.bulk_update(
            addresses,
            fields=[
                SapBpAddress.outside_sales_rep_normalized,
                SapBpAddress.inside_sales_rep_normalized,
                SapBpAddress.corporate_rep_normalized,
            ],
            batch_size=100,
        )

    print(f"Normalized rep names for {len(addresses)} SAP BP address rows")


def _find_staff_by_normalized_name(normalized_name):
    """Look up a StaffAccount by its normalized_name; None if not assigned/not found."""
    if not normalized_name:
        return None
    return StaffAccount.select().where(StaffAccount.normalized_name == normalized_name).first()


def _sync_location_staff(location, sap_address):
    """
    Make a CompanyLocation's assigned staff match SAP's corporate rep and
    inside sales rep (SAP is the source of truth): assign whoever's
    missing, unassign anyone currently assigned who isn't one of those two
    reps, and touch nothing if it already matches.
    Returns "unchanged", "updated", or "error" (userErrors were returned).
    """
    desired_staff_by_shopify_id = {}
    for normalized_name in (sap_address.corporate_rep_normalized, sap_address.inside_sales_rep_normalized):
        staff_account = _find_staff_by_normalized_name(normalized_name)
        if staff_account:
            desired_staff_by_shopify_id[staff_account.shopify_id] = staff_account

    current_assignments = list(
        StaffAssignment.select(StaffAssignment, StaffAccount)
        .join(StaffAccount)
        .where(StaffAssignment.company_location == location)
    )
    current_assignment_by_shopify_id = {
        assignment.staff_account.shopify_id: assignment for assignment in current_assignments
    }

    to_assign_ids = [
        shopify_id
        for shopify_id in desired_staff_by_shopify_id
        if shopify_id not in current_assignment_by_shopify_id
    ]
    to_unassign_ids = [
        shopify_id
        for shopify_id in current_assignment_by_shopify_id
        if shopify_id not in desired_staff_by_shopify_id
    ]

    if not to_assign_ids and not to_unassign_ids:
        return "unchanged"

    had_error = False

    if to_unassign_ids:
        result = remove_staff_from_location(to_unassign_ids, location.shopify_id)
        if result["userErrors"]:
            print(f"  Error unassigning staff from {location.name}: {result['userErrors']}")
            had_error = True
        else:
            unassigned_ids = [current_assignment_by_shopify_id[sid].id for sid in to_unassign_ids]
            StaffAssignment.delete().where(StaffAssignment.id.in_(unassigned_ids)).execute()

    if to_assign_ids:
        result = company_location_assign_staff_members(location.shopify_id, to_assign_ids)
        if result["userErrors"]:
            print(f"  Error assigning staff to {location.name}: {result['userErrors']}")
            had_error = True
        else:
            new_assignments = [
                StaffAssignment(
                    company_location=location,
                    staff_account=desired_staff_by_shopify_id[assigned.get("staffMember", {}).get("id")],
                    shopify_id=assigned.get("id") or "",
                )
                for assigned in result["assigned"]
                if assigned.get("staffMember", {}).get("id") in desired_staff_by_shopify_id
            ]
            if new_assignments:
                StaffAssignment.bulk_create(new_assignments, batch_size=100)

    return "error" if had_error else "updated"


def _find_sap_address_by_external_id(external_id):
    """Find a SapAddress record by its normalized external_id (norm_address_uuid)."""
    if not external_id:
        return None
    normalized = str(external_id).lower().replace(" ", "").replace("_", "").replace("-", "")
    if not normalized:
        return None
    return SapAddress.select().where(SapAddress.norm_address_uuid == normalized).first()


def _get_desired_staff_for_location(sap_address):
    """
    Get the desired staff accounts for a location based on corporate and inside sales reps
    from the SapAddress record. Returns a dict of shopify_id -> StaffAccount.
    Staff names in DB are already normalized to SAP format via _apply_sap_equivalence.
    """
    desired_staff = {}
    
    for normalized_name in (sap_address.corporate_rep_normalized, sap_address.inside_sales_rep_normalized):
        if normalized_name:
            staff_account = StaffAccount.select().where(StaffAccount.normalized_name == normalized_name).first()
            if staff_account:
                desired_staff[staff_account.shopify_id] = staff_account
    return desired_staff


def _sync_location_staff_from_sap_address(location, sap_address):
    """
    Sync staff assignments for a location based on SapAddress corporate and inside sales reps.
    Handles objects internally and converts them to string IDs when calling Shopify.
    Assigns missing staff and removes incorrectly assigned staff.
    Returns a dict with the sync report.
    """
    normalized_external_id = location.external_id.lower().replace(" ", "").replace("_", "").replace("-", "") if location.external_id else ""

    desired_staff_by_shopify_id = _get_desired_staff_for_location(sap_address)
    
    current_assignments = list(
        StaffAssignment.select(StaffAssignment, StaffAccount)
        .join(StaffAccount)
        .where(StaffAssignment.company_location == location)
    )
    current_assignment_by_shopify_id = {
        assignment.staff_account.shopify_id: assignment for assignment in current_assignments
    }

    to_assign_staff = [
        staff
        for shopify_id, staff in desired_staff_by_shopify_id.items()
        if shopify_id not in current_assignment_by_shopify_id
    ]
    to_unassign_assignments = [
        assignment
        for shopify_id, assignment in current_assignment_by_shopify_id.items()
        if shopify_id not in desired_staff_by_shopify_id
    ]

    report = {
        "location_name": location.name,
        "external_id": location.external_id,
        "normalized_external_id": normalized_external_id,
        "sap_address_bp_uuid": sap_address.bp_uuid,
        "staff_to_assign": [
            {
                "name": f"{staff.first_name} {staff.last_name}",
                "staff_id": staff.shopify_id,
            }
            for staff in to_assign_staff
        ],
        "assignments_to_unassign": [
            {
                "name": f"{assignment.staff_account.first_name} {assignment.staff_account.last_name}",
                "staff_id": assignment.staff_account.shopify_id,
                "assignment_id": assignment.shopify_id,
            }
            for assignment in to_unassign_assignments
        ],
        "status": "unchanged",
        "user_errors": [],
        "applied_changes_verified": False,
        "final_assignments": [],
    }

    print(f"  {location.name} | external_id: {location.external_id} | normalized: {normalized_external_id}")
    print(f"  sap_address: {sap_address.bp_uuid}")
    print("  Staff to assign:")
    for staff in to_assign_staff:
        print(f"    - {staff.first_name} {staff.last_name} | staff id: {staff.shopify_id}")
    print("  Assignments to unassign:")
    for assignment in to_unassign_assignments:
        print(f"    - {assignment.staff_account.first_name} {assignment.staff_account.last_name} | staff id: {assignment.staff_account.shopify_id} | assignment id: {assignment.shopify_id}")

    if not to_assign_staff and not to_unassign_assignments:
        report["status"] = "unchanged"
        report["applied_changes_verified"] = True
        report["final_assignments"] = [
            {
                "name": f"{assignment.staff_account.first_name} {assignment.staff_account.last_name}",
                "staff_id": assignment.staff_account.shopify_id,
                "assignment_id": assignment.shopify_id,
            }
            for assignment in current_assignments
        ]
        return report

    had_error = False

    if to_unassign_assignments:
        assignment_ids = [assignment.shopify_id for assignment in to_unassign_assignments]
        result = remove_staff_from_location(assignment_ids)
        if result["userErrors"]:
            print(f"  Error unassigning staff from {location.name}: {result['userErrors']}")
            had_error = True
            report["user_errors"].extend(result["userErrors"])
        else:
            db_ids = [assignment.id for assignment in to_unassign_assignments]
            StaffAssignment.delete().where(StaffAssignment.id.in_(db_ids)).execute()

    if to_assign_staff:
        staff_ids = [staff.shopify_id for staff in to_assign_staff]
        result = company_location_assign_staff_members(location.shopify_id, staff_ids)
        if result["userErrors"]:
            print(f"  Error assigning staff to {location.name}: {result['userErrors']}")
            had_error = True
            report["user_errors"].extend(result["userErrors"])
        else:
            new_assignments = [
                StaffAssignment(
                    company_location=location,
                    staff_account=desired_staff_by_shopify_id[assigned.get("staffMember", {}).get("id")],
                    shopify_id=assigned.get("id") or "",
                )
                for assigned in result["assigned"]
                if assigned.get("staffMember", {}).get("id") in desired_staff_by_shopify_id
            ]
            if new_assignments:
                StaffAssignment.bulk_create(new_assignments, batch_size=100)

    report["status"] = "error" if had_error else "updated"

    # Verify applied changes by re-reading assignments
    final_assignments = list(
        StaffAssignment.select(StaffAssignment, StaffAccount)
        .join(StaffAccount)
        .where(StaffAssignment.company_location == location)
    )
    final_staff_ids = {assignment.staff_account.shopify_id for assignment in final_assignments}
    desired_staff_ids = set(desired_staff_by_shopify_id.keys())
    report["applied_changes_verified"] = final_staff_ids == desired_staff_ids
    report["final_assignments"] = [
        {
            "name": f"{assignment.staff_account.first_name} {assignment.staff_account.last_name}",
            "staff_id": assignment.staff_account.shopify_id,
            "assignment_id": assignment.shopify_id,
        }
        for assignment in final_assignments
    ]

    return report


def match_shopify_company_locations_sap_address():
    """
    Match CompanyLocation records to SapAddress records using external_id (norm_address_uuid).
    For each match, sync staff assignments based on corporate and inside sales reps.
    Processes in batches to avoid memory overload.
    Prints a JSON report at the end with all sync results.
    """
    print("Starting match of Shopify company locations to SAP addresses...")

    batch_size = 1000
    processed_count = 0
    total_locations = CompanyLocation.select().count()
    sync_reports = []

    while processed_count < total_locations:
        batch = list(
            CompanyLocation.select()
            .limit(batch_size)
            .offset(processed_count)
        )

        if not batch:
            break

        for location in batch:
            sap_address = _find_sap_address_by_external_id(location.external_id)
            
            if sap_address:
                report = _sync_location_staff_from_sap_address(location, sap_address)
                sync_reports.append(report)
                print(f"  {location.name}: {report['status']}")
            else:
                no_match_report = {
                    "location_name": location.name,
                    "external_id": location.external_id,
                    "normalized_external_id": location.external_id.lower().replace(" ", "").replace("_", "").replace("-", "") if location.external_id else "",
                    "sap_address_bp_uuid": None,
                    "staff_to_assign": [],
                    "assignments_to_unassign": [],
                    "status": "no_match",
                    "user_errors": [],
                    "applied_changes_verified": False,
                    "final_assignments": [],
                }
                sync_reports.append(no_match_report)
                print(f"  {location.name}: no matching SAP address found")

        processed_count += len(batch)
        print(f"Processed {processed_count}/{total_locations} company locations")

    report_filename = f"reporte-{date.today().isoformat()}.json"
    with open(report_filename, "w", encoding="utf-8") as f:
        json.dump(sync_reports, f, indent=2, ensure_ascii=False)

    print("\n\n===== SYNC REPORT (JSON) =====")
    print(json.dumps(sync_reports, indent=2))
    print(f"\nReport saved to: {report_filename}")
    print("===== END SYNC REPORT =====\n")


def main():
    batch_companies_and_locations()
    batch_sap_bp_addresses()
    batch_sap_addresses()
    normalize_sap_bp_address_reps()
    normalize_sap_address_reps()
    match_shopify_company_locations_sap_address()


if __name__ == "__main__":
    main()
