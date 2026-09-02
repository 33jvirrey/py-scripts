from peewee import *
from playhouse.migrate import SqliteMigrator, migrate

db = SqliteDatabase("database.db")

class Company(Model):
    shopify_id = CharField()
    sap_id = CharField()
    external_id = CharField()

    name = CharField()

    class Meta:
        database = db


class CompanyLocation(Model):
    company = ForeignKeyField(Company, backref="locations")
    # Shopify company id (gid://shopify/Company/...) duplicated here so
    # locations can be queried/joined without going through the local FK.
    company_shopify_id = CharField(default="")
    sap_id = CharField()
    name = CharField()
    external_id = CharField()
    shopify_id = CharField()
    
    validated = BooleanField(default=False)

    class Meta:
        database = db

class StaffAccount(Model):
    shopify_id = CharField()
    email = CharField()
    first_name = CharField(default="")
    last_name = CharField(default="")

    # first_name + last_name joined, lowercased, spaces removed - for
    # matching against SapBpAddress's normalized rep columns.
    normalized_name = CharField(null=True)

    class Meta:
        database = db


class StaffAssignment(Model):
    """Links a StaffAccount to a CompanyLocation, mirroring Shopify's
    CompanyLocationStaffMemberAssignment."""
    company_location = ForeignKeyField(CompanyLocation, backref="staff_assignments")
    staff_account = ForeignKeyField(StaffAccount, backref="assignments")
    shopify_id = CharField()

    class Meta:
        database = db


class SapBpAddress(Model):
    """
    Rows from the SAP ByDesign RPBUPCSD_Q0001QueryResults analytics query.
    Column names are the human-readable characteristic names from the SAP
    query designer; see sap.BP_ADDRESS_FIELD_MAP for the mapping back to
    the technical OData field codes.
    """
    account_id = CharField(default="")
    account_text = CharField(default="")
    account_id_id = CharField(default="")
    account_id_text = CharField(default="")
    address_id = CharField(default="")
    bp_uuid_address_id = CharField(default="")
    address_line_1_id = CharField(default="")
    address_line_2_id = CharField(default="")
    address_line_4_id = CharField(default="")
    outside_sales_rep_id = CharField(default="")
    outside_sales_rep_text = CharField(default="")
    inside_sales_rep_id = CharField(default="")
    inside_sales_rep_text = CharField(default="")
    corporate_rep_id = CharField(default="")
    corporate_rep_text = CharField(default="")

    # Normalized (lowercased, spaces stripped) rep names for matching;
    # "not assigned"/empty values are stored as NULL, not a name.
    outside_sales_rep_normalized = CharField(null=True)
    inside_sales_rep_normalized = CharField(null=True)
    corporate_rep_normalized = CharField(null=True)

    class Meta:
        database = db


class SapAddress(Model):
    """
    Rows from the SAP ByDesign RPZ354E43506089F046ADF360QueryResults analytics query.
    Contains detailed address information for business partners.
    """
    bp_uuid = CharField(default="")
    address_uuid = CharField(default="")
    address_usage_code_id = CharField(default="")
    building_id = CharField(default="")
    city_id = CharField(default="")
    country_id = CharField(default="")
    country_text = CharField(default="")
    county_id = CharField(default="")
    customer_uuid = CharField(default="")
    district_id = CharField(default="")
    email_uri_id = CharField(default="")
    email_id = CharField(default="")
    house_id = CharField(default="")
    main_address_id = CharField(default="")
    po_box_dev_city_id = CharField(default="")
    po_box_dev_country_id = CharField(default="")
    po_box_dev_country_text = CharField(default="")
    po_box_dev_region_text = CharField(default="")
    po_box_id = CharField(default="")
    po_box_postal_code_id = CharField(default="")
    region_id = CharField(default="")
    region_text = CharField(default="")
    room_id = CharField(default="")
    status_id = CharField(default="")
    status_text = CharField(default="")
    street_id = CharField(default="")
    street_postal_code_id = CharField(default="")
    street_prefix_id = CharField(default="")
    street_suffix_id = CharField(default="")
    studio_address_id = CharField(default="")
    tax_jurisdiction_text = CharField(default="")
    time_zone_id = CharField(default="")
    time_zone_text = CharField(default="")
    website_id = CharField(default="")
    
    corporate_rep_normalized = CharField(null=True)
    inside_sales_rep_normalized = CharField(null=True)
    outside_sales_rep_normalized = CharField(null=True)
    norm_address_uuid = CharField(null=True)

    class Meta:
        database = db

db.connect()

# SapBpAddress column names changed from raw SAP field codes to readable
# names; it's a fully re-fetchable cache, so just rebuild it if stale.
if "sapbpaddress" in db.get_tables():
    _sap_columns = {col.name for col in db.get_columns("sapbpaddress")}
    if "account_id" not in _sap_columns:
        db.drop_tables([SapBpAddress])

db.create_tables([Company, CompanyLocation, StaffAccount, StaffAssignment, SapBpAddress, SapAddress])

_migrator = SqliteMigrator(db)

_address_columns = {col.name for col in db.get_columns("sapaddress")}
if "corporate_rep_normalized" not in _address_columns:
    migrate(_migrator.add_column("sapaddress", "corporate_rep_normalized", CharField(null=True)))
if "inside_sales_rep_normalized" not in _address_columns:
    migrate(_migrator.add_column("sapaddress", "inside_sales_rep_normalized", CharField(null=True)))
if "outside_sales_rep_normalized" not in _address_columns:
    migrate(_migrator.add_column("sapaddress", "outside_sales_rep_normalized", CharField(null=True)))
if "norm_address_uuid" not in _address_columns:
    migrate(_migrator.add_column("sapaddress", "norm_address_uuid", CharField(null=True)))

# Add columns introduced after the tables already existed in database.db.