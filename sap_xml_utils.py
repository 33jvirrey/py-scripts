import requests
import xml.etree.ElementTree as ET

# SAP configuration (kept here as requested)
WS_URL = "https://my360636.sapbydesign.com/sap/bc/srt/scs/sap/managesalesorderin5"
USERNAME = "AVIRREY"
PASSWORD = "5-iU{F=&_Yn$@,fd"
PRICECOMP_UUID = "fa163e98-34a6-1fe0-aecf-4575b2b2ff75"
CURRENCY = "USD"


def build_update_price_payload(order_id, item_id, pricecomp_uuid, new_price, currency):
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
            <ItemPriceComponent actionCode="02">
              <UUID>{pricecomp_uuid}</UUID>
              <Rate>
                <DecimalValue>{new_price}</DecimalValue>
                <CurrencyCode>{currency}</CurrencyCode>
                <BaseDecimalValue>1.0</BaseDecimalValue>
                <BaseMeasureUnitCode>EA</BaseMeasureUnitCode>
              </Rate>
            </ItemPriceComponent>
          </PriceAndTaxCalculationItem>
        </Item>
      </SalesOrder>
    </n0:SalesOrderBundleMaintainRequest_sync>
  </soapenv:Body>
</soapenv:Envelope>"""


def build_query_by_id_payload(order_id):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:n0="http://sap.com/xi/SAPGlobal20/Global">
  <soapenv:Header/>
  <soapenv:Body>
    <n0:SalesOrderByElementsQuery_sync>
      <SalesOrderSelectionByElements>
        <SelectionByID>
          <InclusionExclusionCode>I</InclusionExclusionCode>
          <IntervalBoundaryTypeCode>1</IntervalBoundaryTypeCode>
          <LowerBoundaryID>{order_id}</LowerBoundaryID>
        </SelectionByID>
      </SalesOrderSelectionByElements>
    </n0:SalesOrderByElementsQuery_sync>
  </soapenv:Body>
</soapenv:Envelope>"""


def send_soap(xml_body, soap_action):
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": soap_action,
    }
    r = requests.post(
        WS_URL,
        data=xml_body.encode("utf-8"),
        auth=(USERNAME, PASSWORD),
        headers=headers,
        timeout=60,
        verify=True,
    )
    if r.status_code != 200 or "<Fault>" in r.text:
        raise Exception("SOAP call failed")
    return r.text


def update_item_price(order_id, item_id, new_price, pricecomp_uuid: str | None = None, currency: str | None = None):
    pc_uuid = pricecomp_uuid or PRICECOMP_UUID
    curr = currency or CURRENCY
    xml = build_update_price_payload(order_id, item_id, pc_uuid, new_price, curr)
    return send_soap(xml, "https://my360636.sapbydesign.com/sap/bc/srt/scs/sap/managesalesorderin5")


def get_sales_order_xml(order_id):
    xml = build_query_by_id_payload(order_id)
    return send_soap(xml, "http://sap.com/xi/SAPGlobal20/Global/SalesOrderByElementsQuery_sync")


def _text(el):
    return el.text.strip() if el is not None and el.text is not None else ""


def _findall_desc(root, name_suffix):
    for elem in root.iter():
        if elem.tag.endswith(name_suffix):
            yield elem


def get_item_id_by_sku_from_order_xml(order_xml_text, sku_product):
    root = ET.fromstring(order_xml_text)
    for item in _findall_desc(root, "Item"):
        prod = None
        for cand in ("ProductID", "ProductInternalID", "Product"):
            for e in item:
                if e.tag.endswith(cand):
                    prod = _text(e)
                    break
            if prod:
                break
        if prod and prod == sku_product:
            for e in item:
                if e.tag.endswith("ID"):
                    return _text(e)
    return ""


def get_current_item_price_from_order_xml(order_xml_text, item_id, pricecomp_uuid):
    root = ET.fromstring(order_xml_text)
    for item in _findall_desc(root, "Item"):
        item_id_val = ""
        for e in item:
            if e.tag.endswith("ID"):
                item_id_val = _text(e)
                break
        if item_id_val != str(item_id):
            continue
        for ipc in _findall_desc(item, "ItemPriceComponent"):
            uuid = None
            for child in ipc:
                if child.tag.endswith("UUID"):
                    uuid = _text(child)
                    break
            if uuid and uuid == pricecomp_uuid:
                for rate in _findall_desc(ipc, "Rate"):
                    for dv in rate:
                        if dv.tag.endswith("DecimalValue"):
                            return _text(dv)
    return ""


def get_item_id_by_sku(order_id, sku_product):
    order_xml = get_sales_order_xml(order_id)
    return get_item_id_by_sku_from_order_xml(order_xml, sku_product)


def get_current_item_price(order_id, item_id, pricecomp_uuid=None):
    order_xml = get_sales_order_xml(order_id)
    return get_current_item_price_from_order_xml(order_xml, item_id, pricecomp_uuid or PRICECOMP_UUID)
