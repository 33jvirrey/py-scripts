import pandas as pd
import os
from decimal import Decimal, InvalidOperation
from sap_xml_utils import (
    get_item_id_by_sku,
    get_current_item_price,
    update_item_price as util_update_item_price,
)

CSV_PATH       = "update_prices.csv"
INPUT_CSV      = "input_updates.csv"

def _to_decimal(s):
    try:
        return Decimal(str(s))
    except (InvalidOperation, ValueError):
        return None


def process_csv(input_csv):
    if not os.path.exists(input_csv):
        raise FileNotFoundError(input_csv)
    df = pd.read_csv(input_csv, dtype=str).fillna("")
    required = {"sales_order_id", "sku_product", "new_price"}
    if not required.issubset(set([c.strip() for c in df.columns.tolist()])):
        raise ValueError("CSV must include: sales_order_id, sku_product, new_price")
    for row in df.itertuples(index=False):
        so_id = getattr(row, "sales_order_id", "").strip()
        sku = getattr(row, "sku_product", "").strip()
        new_price = getattr(row, "new_price", "").strip()
        item_id = getattr(row, "item_id", "").strip() if ("item_id" in df.columns) else ""
        if not item_id:
            item_id = get_item_id_by_sku(so_id, sku)
            if not item_id:
                continue
        current_price = get_current_item_price(so_id, item_id)
        d_curr = _to_decimal(current_price)
        d_new = _to_decimal(new_price)
        if d_curr is None or d_new is None:
            continue
        if d_curr == d_new:
            resp_text = util_update_item_price(so_id, item_id, new_price)
            print("Response body:")
            print(resp_text)




if __name__ == "__main__":
    process_csv(INPUT_CSV)
