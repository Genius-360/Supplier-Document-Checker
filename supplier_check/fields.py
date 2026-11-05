"""The fields we read from every quotation. Used by the LLM prompt AND by verification."""

# (name, kind, description). kind: text | number | bool | enum:a|b|c
FIELD_SPECS = [
    ("supplier_name", "text", "Supplier's name as printed at the top of the quotation."),
    ("quotation_no", "text", "Quotation number."),
    ("quotation_date", "text", "Quotation date exactly as written, e.g. 2026-10-21."),
    ("pr_reference", "text", "Purchase request reference the quotation answers, e.g. PR-2026-114."),
    ("item_code", "text", "Item letter of the single line item (A, B, C, D or E)."),
    ("item_description", "text", "Description of the line item."),
    ("quantity", "number", "Quantity quoted for the line item."),
    ("unit", "text", "Unit of the quantity, e.g. metre, piece, cone."),
    ("unit_price", "number", "Unit price in BDT exactly as printed. Do not convert or adjust it."),
    ("line_amount", "number", "Amount printed on the line item row."),
    ("subtotal", "number", "Subtotal printed on the quotation. null if there is none."),
    ("vat_rate_pct", "number", "VAT percentage printed on a separate VAT line, e.g. 15. null if there is no separate VAT line."),
    ("vat_amount", "number", "VAT amount printed on a separate VAT line. null if there is none."),
    ("total", "number", "Total printed on the quotation."),
    ("price_includes_vat", "bool", "true ONLY if the document says prices already include VAT/taxes. Otherwise false."),
    ("tin", "text", "Supplier TIN number. null if no TIN number is printed."),
    ("bin", "text", "Supplier BIN number. null if no BIN number is printed."),
    ("advance_pct", "number", "Percent of the order paid in advance with the purchase order. 0 if the document says no advance is required. null if not stated."),
    ("payment_days_min", "number", "Days after delivery by which payment is due. Lower bound if a range ('30 to 90 days'), otherwise the single number. null if no number of days is stated."),
    ("payment_days_max", "number", "Upper bound of the same payment period (equal to the lower bound if a single number). null if no number of days is stated."),
    ("delivery_value", "number", "The number in the delivery promise, e.g. 4 in 'within 4 weeks'. null if there is none."),
    ("delivery_unit", "enum:days|weeks|months", "Unit of that delivery number."),
    ("penalty_clause_present", "bool", "true if the document contains any late-delivery penalty / delay clause, otherwise false."),
    ("penalty_pct", "number", "Penalty percentage as printed, e.g. 0.75 for '0.75%'. null if there is none."),
    ("penalty_period", "enum:week|day|month|other", "Period that the penalty percentage applies to."),
    ("penalty_base", "enum:order_value|other|not_stated", "What the penalty percentage is applied to."),
    ("validity_days", "number", "Number of days the quotation stays valid. null if not stated."),
]

KIND = {name: ("enum" if kind.startswith("enum") else kind) for name, kind, _ in FIELD_SPECS}
ENUM_VALUES = {
    name: kind.split(":", 1)[1].split("|") for name, kind, _ in FIELD_SPECS if kind.startswith("enum")
}
FIELD_NAMES = [name for name, _, _ in FIELD_SPECS]
