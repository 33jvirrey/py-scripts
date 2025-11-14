import requests
import pandas as pd

WS_URL = "https://my360636.sapbydesign.com/sap/bc/srt/scs/sap/managesalesorderin5"

USERNAME = "FVARGAS"
PASSWORD = "RedEyes.2022!"

SALES_ORDER_ID = "679307"
ITEM_ID        = "20"
NEW_UNIT_PRICE = "222"  # <-- put your new unit price here
CURRENCY       = "USD"


def build_update_price_payload(order_id, item_id,  new_price, currency):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:n0="http://sap.com/xi/SAPGlobal20/Global">
  <soapenv:Header/>
  <soapenv:Body>
<n0:SalesOrderBundleMaintainRequest_sync>
<BasicMessageHeader/>
<SalesOrder actionCode="02">
<ID>{order_id}</ID>
<Item actionCode="02">
<ID>{item_id}</ID>
<PriceAndTaxCalculationItem actionCode="02">
<ItemMainPrice actionCode="04">
<Rate>
<DecimalValue>{new_price}</DecimalValue>
<CurrencyCode>{currency}</CurrencyCode>
<BaseDecimalValue>1.0</BaseDecimalValue>
<BaseMeasureUnitCode>EA</BaseMeasureUnitCode>
</Rate>
</ItemMainPrice>
</PriceAndTaxCalculationItem>
</Item>
</SalesOrder>
</n0:SalesOrderBundleMaintainRequest_sync>
  </soapenv:Body>
</soapenv:Envelope>"""


def update_item_price():
    payload = build_update_price_payload(
        SALES_ORDER_ID,
        ITEM_ID,
        NEW_UNIT_PRICE,
        CURRENCY,
    )

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://sap.com/xi/SAPGlobal20/Global/SalesOrderBundleMaintainRequest_sync",
    }

    response = requests.post(
        WS_URL,
        data=payload.encode("utf-8"),
        auth=(USERNAME, PASSWORD),
        headers=headers,
        timeout=60,
        verify=True,
    )

    print("HTTP status:", response.status_code)
    print("Response body:")
    print(response.text)

    # Quick sanity check
    if response.status_code != 200 or "<Fault>" in response.text:
        raise Exception("SOAP call failed, see response above.")


def _to_str_no_decimal(val):
    try:
        # Handles values like 10.0 coming from CSV as floats
        ival = int(val)
        return str(ival)
    except Exception:
        return str(val)


def process_updates_csv(csv_path: str = "input_updates.csv"):
    df = pd.read_csv(csv_path)
    results = []
    for idx, row in df.iterrows():
        order_id = _to_str_no_decimal(row["sales_order_id"])  # e.g. 679322
        item_id = _to_str_no_decimal(row["line_item"])       # e.g. 10
        new_price = str(row["new_price"])                    # keep as string for XML

        xml = build_update_price_payload(order_id, item_id, new_price, CURRENCY)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "http://sap.com/xi/SAPGlobal20/Global/SalesOrderBundleMaintainRequest_sync",
        }
        response_text = ""
        try:
            r = requests.post(
                WS_URL,
                data=xml.encode("utf-8"),
                auth=(USERNAME, PASSWORD),
                headers=headers,
                timeout=60,
                verify=True,
            )
            response_text = r.text
            print("SOAP Response:")
            print(response_text)
            status = "ok" if r.status_code == 200 and "<Fault>" not in r.text else "error"
        except Exception as e:
            response_text = str(e)
            print("SOAP Response (error):")
            print(response_text)
            status = "error"

        results.append({
            "sales_order_id": order_id,
            "line_item": item_id,
            "new_price": new_price,
            "request_xml": xml,
            "response_xml": response_text,
            "status": status,
        })

    pd.DataFrame(results).to_csv("input_updates_results.csv", index=False)


if __name__ == "__main__":
    process_updates_csv("input_updates.csv")

