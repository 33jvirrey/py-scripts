import requests

WS_URL = "https://my360636.sapbydesign.com/sap/bc/srt/scs/sap/managesalesorderin5"

USERNAME = "FVARGAS"
PASSWORD = "RedEyes.2022!"

SALES_ORDER_ID = "679322"
ITEM_ID        = "10"
NEW_UNIT_PRICE = "1000"  # <-- put your new unit price here
CURRENCY       = "USD"


def build_update_price_payload(order_id, item_id, new_price, currency):
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


if __name__ == "__main__":
    update_item_price()
