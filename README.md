# shopify-reassign-staff-from-sap

Syncs Shopify B2B company location staff assignments (corporate rep / inside sales rep)
to match SAP ByDesign, using SAP as the source of truth. Data is staged locally in a
SQLite database (`database.db`) via [peewee](https://docs.peewee-orm.com/), then diffed
and pushed back to Shopify via its Admin GraphQL API.

## Requirements

A `.env` file with:

- `SAP_BYD_BASE_URL`, `SAP_BYD_USERNAME`, `SAP_BYD_PASSWORD` — SAP ByDesign OData credentials
- `SHOPIFY_STORE_URL`, `SHOPIFY_ACCESS_TOKEN` — Shopify Admin API credentials

## Files

### [index.py](index.py)

Entry point and orchestration. `main()` runs the full pipeline in order:

1. `batch_companies_and_locations()` — wipes and re-fetches `Company`, `CompanyLocation`,
   and `StaffAssignment` from Shopify. Companies come either from `paginate_companies()`
   (every company) or, when `test_list` is non-empty, from `get_companies_by_ids()`
   restricted to those ids (used for testing against a couple of companies). Locations
   are fetched per-company in parallel (15 threads) via `paginate_company_locations()`,
   since some companies have thousands of locations; each location's current staff
   assignments are captured at the same time.
2. `batch_sap_bp_addresses()` — wipes and re-fetches every row of the SAP
   `RPBUPCSD_Q0001QueryResults` analytics query into `SapBpAddress`, paging with
   `fetch_bp_addresses_page()`.
3. `batch_sap_addresses()` — wipes and re-fetches every row of the SAP
   `RPZ354E43506089F046ADF360QueryResults` analytics query into `SapAddress`, paging with
   `fetch_addresses_page()`.
4. `normalize_sap_bp_address_reps()` — fills in `SapBpAddress`'s
   `*_rep_normalized` columns (lowercased, no spaces, "not assigned" → `NULL`) from the
   raw `*_rep_text` columns fetched from SAP.
5. `normalize_sap_address_reps()` — for each `SapAddress` row, looks up the matching
   `SapBpAddress` by `bp_uuid` (SapAddress) / `account_id` (SapBpAddress) and copies over
   its normalized rep names; also normalizes `address_uuid` into `norm_address_uuid` for
   matching against Shopify locations' `external_id`.
6. `match_shopify_company_locations_sap_address()` — for every `CompanyLocation`, finds
   the matching `SapAddress` by normalized `external_id`, then calls
   `_sync_location_staff_from_sap_address()` to make the location's assigned Shopify
   staff match SAP's corporate rep + inside sales rep: assigns whoever's missing,
   unassigns anyone not one of those two reps, and leaves matching locations untouched.
   Writes a per-location JSON report (assigned/unassigned staff, errors, verification)
   to `reporte-<today>.json` and prints it to stdout.

Other helpers in this file:

- `_save_company` / `_build_location_records` — map raw Shopify GraphQL nodes onto
  `Company` / `CompanyLocation` model instances.
- `_get_or_create_staff_account` — upserts a `StaffAccount` from a Shopify staff member
  node, keeping name/email in sync, and computes its `normalized_name` (used to match
  against SAP rep names).
- `_apply_sap_equivalence` / `STAFF_NAME_EQUIVALENCES` — maps known naming mismatches
  between Shopify staff names and SAP rep names (e.g. `jenmcsween` → `jennifermcsween`).
- `_normalize_rep_name` — shared normalization: lowercase, strip spaces, `NULL` for
  empty/"not assigned".
- `_find_staff_by_normalized_name`, `_find_sap_address_by_external_id`,
  `_get_desired_staff_for_location` — lookup helpers used during the sync step.
- `_sync_location_staff` — an earlier/alternate sync path (matches by SAP rep names
  directly against a location, without going through `SapAddress`); superseded by
  `_sync_location_staff_from_sap_address` in the current pipeline but left in place.

### [shopify.py](shopify.py)

Thin wrapper around the Shopify Admin GraphQL API (`/admin/api/2024-01/graphql.json`).

- `paginate_companies()` — pages through all companies (250/page), returning `id`,
  `name`, `externalId`, and the `sap_account_id` metafield.
- `get_companies_by_ids(ids)` — fetches specific companies by gid via the `nodes` query
  (used for the `test_list` restricted runs).
- `paginate_company_locations(company_id)` — pages through a company's locations
  (250/page), returning each location's `id`, `name`, `externalId`, its
  `custom.sap_account_id` metafield, and its current `staffMemberAssignments`.
- `company_location_assign_staff_members(location_id, staff_ids)` — runs the
  `companyLocationAssignStaffMembers` mutation; returns `{"assigned": [...], "userErrors": [...]}`.
- `remove_staff_from_location(assignment_ids)` — runs the
  `companyLocationRemoveStaffMembers` mutation to unassign staff by assignment id;
  returns `{"removed_ids": [...], "userErrors": [...]}`.

### [sap.py](sap.py)

Thin wrapper around two SAP ByDesign analytics OData query services.

- `fetch_bp_addresses_page(skip)` — fetches one `PAGE_SIZE` (5000-row) page of the
  `RPBUPCSD_Q0001QueryResults` query (business partner sales rep assignments) via
  `$top`/`$skip`, since this analytics endpoint doesn't support cursor-based paging.
- `fetch_addresses_page(skip)` — same pattern for the `RPZ354E43506089F046ADF360QueryResults`
  query (detailed business partner address data).
- `BP_ADDRESS_FIELDS` / `ADDRESS_FIELDS` — the technical SAP OData field codes selected
  from each query.
- `BP_ADDRESS_FIELD_MAP` / `ADDRESS_FIELD_MAP` — map each technical field code to a
  readable column name, used both for `$select` and to build the DB records.

### [db.py](db.py)

Peewee models and SQLite schema (`database.db`), plus lightweight migrations that run on
import.

- `Company` — Shopify company (`shopify_id`, `sap_id`, `external_id`, `name`).
- `CompanyLocation` — Shopify company location, FK to `Company`; also stores
  `company_shopify_id` denormalized for querying without a join.
- `StaffAccount` — a Shopify staff member (`shopify_id`, `email`, `first_name`,
  `last_name`, `normalized_name`).
- `StaffAssignment` — links a `StaffAccount` to a `CompanyLocation`, mirroring Shopify's
  `CompanyLocationStaffMemberAssignment`.
- `SapBpAddress` — raw cache of the `RPBUPCSD_Q0001QueryResults` SAP query (business
  partner + sales rep names), plus normalized rep name columns.
- `SapAddress` — raw cache of the `RPZ354E43506089F046ADF360QueryResults` SAP query
  (detailed address data), plus normalized rep name columns copied over from the
  matching `SapBpAddress`, and `norm_address_uuid` for matching to Shopify locations.
- On import: creates all tables if missing, drops and recreates `SapBpAddress` if it's
  using the old raw-field-code column names (it's a fully re-fetchable cache), and adds
  the `*_normalized` / `norm_address_uuid` columns to `SapAddress` if not already present.

## Output

Running the pipeline (`python index.py`) produces:

- `database.db` — the staged SQLite cache of Shopify + SAP data.
- `reporte-<YYYY-MM-DD>.json` — a report of every location processed in the final sync
  step: matched SAP address, staff assigned/unassigned, any Shopify `userErrors`, and a
  post-sync verification of the final assignments.
