import os
import requests
from dotenv import load_dotenv

#Env Configuration, SAP keys and Shopify Endpoints. Get from the .env file
load_dotenv()

SHOPIFY_STORE_URL = os.getenv("SHOPIFY_STORE_URL")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN")

ENDPOINT = f"{SHOPIFY_STORE_URL}/admin/api/2024-01/graphql.json"

print("ENDPOINT", ENDPOINT)
HEADERS = {
    "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
    "Content-Type": "application/json",
}

print("✓ Shopify pagination functions loaded")


def paginate_companies():
    counter_requests = 0
    after = None
    companies = []

    while True:
        query = """
        query Companies($after: String) {
            companies(first: 250, after: $after) {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        id
                        name
                        externalId
                        metafield(namespace: "sap_account_id", key: "sap_account_id") {
                            value
                        }
                    }
                }
            }
        }
        """
        variables = {"after": after}

        response = requests.post(
            ENDPOINT,
            headers=HEADERS,
            json={"query": query, "variables": variables},
        )
        response.raise_for_status()
        payload = response.json()

        data = payload.get("data", {}).get("companies") or {}
        edges = data.get("edges", [])

        print(f"Requests: {counter_requests}, retrieved: {len(edges)} companies")

        for edge in edges:
            companies.append(edge.get("node"))

        if not data.get("pageInfo", {}).get("hasNextPage"):
            break

        after = data.get("pageInfo", {}).get("endCursor")
        counter_requests += 1

    print(f"Total requests: {counter_requests}")
    return companies


def get_companies_by_ids(company_shopify_ids):
    """
    Fetch specific companies directly by their Shopify gid via the `nodes`
    query, instead of paginating through every company and filtering
    client-side. Used when test_list restricts a batch to a few companies.
    """
    if not company_shopify_ids:
        return []

    query = """
    query CompaniesByIds($ids: [ID!]!) {
        nodes(ids: $ids) {
            ... on Company {
                id
                name
                externalId
                metafield(namespace: "sap_account_id", key: "sap_account_id") {
                    value
                }
            }
        }
    }
    """
    variables = {"ids": company_shopify_ids}

    response = requests.post(
        ENDPOINT,
        headers=HEADERS,
        json={"query": query, "variables": variables},
    )
    response.raise_for_status()
    payload = response.json()

    nodes = payload.get("data", {}).get("nodes") or []
    return [node for node in nodes if node]


def paginate_company_locations(company_id: str):
    after = None
    locations = []

    while True:
        query = """
        query CompanyLocations($companyId: ID!, $after: String) {
            company(id: $companyId) {
                id
                locations(first: 250, after: $after) {
                    pageInfo { hasNextPage endCursor }
                    edges {
                        node {
                            id
                            name
                            externalId
                            metafield(namespace: "custom", key: "sap_account_id") {
                                value
                            }
                            staffMemberAssignments(first: 50) {
                                nodes {
                                    id
                                    staffMember {
                                        id
                                        firstName
                                        lastName
                                        email
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        variables = {"companyId": company_id, "after": after}

        response = requests.post(
            ENDPOINT,
            headers=HEADERS,
            json={"query": query, "variables": variables},
        )
        response.raise_for_status()
        payload = response.json()

        company_data = payload.get("data", {}).get("company") or {}
        data = company_data.get("locations") or {}
        edges = data.get("edges", [])

        for edge in edges:
            locations.append(edge.get("node"))

        if not data.get("pageInfo", {}).get("hasNextPage"):
            break

        after = data.get("pageInfo", {}).get("endCursor")

    return locations


def company_location_assign_staff_members(company_location_id, staff_member_ids):
    """
    Assign one or more staff members to a company location.
    Returns {"assigned": [...], "userErrors": [...]}.
    """
    query = """
    mutation AssignStaff($companyLocationId: ID!, $staffMemberIds: [ID!]!) {
        companyLocationAssignStaffMembers(companyLocationId: $companyLocationId, staffMemberIds: $staffMemberIds) {
            companyLocationStaffMemberAssignments {
                id
                staffMember { id email }
                companyLocation { id name }
            }
            userErrors { field message }
        }
    }
    """

    payload = {
        "query": query,
        "variables": {
            "companyLocationId": company_location_id,
            "staffMemberIds": staff_member_ids,
        },
    }

    response = requests.post(ENDPOINT, headers=HEADERS, json=payload)
    response.raise_for_status()
    data = response.json().get("data", {})
    result = data.get("companyLocationAssignStaffMembers", {})

    return {
        "assigned": result.get("companyLocationStaffMemberAssignments") or [],
        "userErrors": result.get("userErrors") or [],
    }


def remove_staff_from_location(company_location_staff_member_assignment_ids):
    """
    Remove one or more staff members from a company location.
    company_location_staff_member_assignment_ids: list of company location staff member assignment IDs.
    Returns {"removed_ids": [...], "userErrors": [...]}.
    """
    print(f"Removing company location staff member assignments: {company_location_staff_member_assignment_ids}")

    query = """
    mutation companyLocationRemoveStaffMembers($companyLocationStaffMemberAssignmentIds: [ID!]!) {
        companyLocationRemoveStaffMembers(
            companyLocationStaffMemberAssignmentIds: $companyLocationStaffMemberAssignmentIds
        ) {
            deletedCompanyLocationStaffMemberAssignmentIds
            userErrors { field message }
        }
    }
    """

    variables = {
        "companyLocationStaffMemberAssignmentIds": company_location_staff_member_assignment_ids,
    }

    response = requests.post(
        ENDPOINT,
        headers=HEADERS,
        json={"query": query, "variables": variables},
    )
    response.raise_for_status()
    data = response.json().get("data", {})
    result = data.get("companyLocationRemoveStaffMembers", {})

    return {
        "removed_ids": result.get("deletedCompanyLocationStaffMemberAssignmentIds") or [],
        "userErrors": result.get("userErrors") or [],
    }
