"""
test_odoo_fields.py — Discover the EXACT custom field names on crm.lead.

Run this FIRST before updating any code:
    cd erp-ai-backend
    python test_odoo_fields.py

Connects to Odoo via xmlrpc.client, calls fields_get() on crm.lead,
then filters and prints ONLY fields whose name contains "ai" or starts
with "x_".  This tells us the canonical field names added by the
crm_ai_assistant module.

Expected output (once the module is installed):
    ai_summary                → Text field
    ai_priority_prediction    → Selection field (high/medium/low)
    ai_email_draft            → Text field

    OR with Odoo Studio / x_ prefix:
    x_ai_summary
    x_ai_priority_prediction
    x_ai_email_draft
"""

import xmlrpc.client
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # fall back to env vars / defaults

# ── Connection settings ────────────────────────────────────────────────────────
URL      = os.getenv("ODOO_URL",      "http://localhost:8070")
DB       = os.getenv("ODOO_DB",       "odoo")
USERNAME = os.getenv("ODOO_USERNAME", "odoo@gmail.com")
PASSWORD = os.getenv("ODOO_PASSWORD", "odoo")

print(f"Connecting to Odoo at {URL}  (db={DB}, user={USERNAME})")
print("-" * 60)

# ── Authenticate ───────────────────────────────────────────────────────────────
common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
try:
    uid = common.authenticate(DB, USERNAME, PASSWORD, {})
except Exception as e:
    print(f"ERROR — could not reach Odoo: {e}")
    sys.exit(1)

if not uid:
    print("ERROR — authentication failed (bad credentials or DB name).")
    sys.exit(1)

print(f"Authenticated — uid={uid}")
print("-" * 60)

models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

# ── Check if crm_ai_assistant module is installed ─────────────────────────────
ai_mods = models.execute_kw(DB, uid, PASSWORD,
    "ir.module.module", "search_read",
    [[["name", "ilike", "crm_ai"]]],
    {"fields": ["name", "shortdesc", "state"]}
)
if ai_mods:
    print("crm_ai_assistant module status:")
    for m in ai_mods:
        print(f"  [{m['state']}] {m['name']} — {m['shortdesc']}")
else:
    print("WARNING: No module matching 'crm_ai' found in the module list.")
    print("         The crm_ai_assistant module may not be installed yet.")
print()

# ── Fetch ALL fields on crm.lead via fields_get ────────────────────────────────
# NOTE: fields_get takes no positional model args — pass all options as kwargs.
try:
    all_fields: dict = models.execute_kw(
        DB, uid, PASSWORD,
        "crm.lead", "fields_get",
        [],  # no positional args
        {"attributes": ["string", "type", "required", "readonly", "help"]},
    )
except Exception as e:
    print(f"ERROR calling fields_get on crm.lead: {e}")
    sys.exit(1)

print(f"Total crm.lead fields returned by fields_get(): {len(all_fields)}")

# ── Filter for AI / custom / x_ fields ────────────────────────────────────────
ai_fields     = {k: v for k, v in all_fields.items() if "ai" in k.lower()
                 and k not in ("email_from", "email_cc", "email_normalized",
                               "email_state", "email_domain_criterion",
                               "partner_email_update", "campaign_id")}
x_fields      = {k: v for k, v in all_fields.items() if k.startswith("x_")}
studio_fields = {k: v for k, v in all_fields.items() if "studio" in k.lower()}

# Merge all into one deduplicated dict
combined = {**ai_fields, **x_fields, **studio_fields}

print(f"Fields with 'ai' in name (excl. email/*):  {len(ai_fields)}")
print(f"Fields starting with 'x_':                 {len(x_fields)}")
print(f"Fields containing 'studio':                {len(studio_fields)}")
print(f"Unique combined (ai + x_ + studio):        {len(combined)}")
print("=" * 60)

if not combined:
    print()
    print("NO custom AI fields found on crm.lead.")
    print()
    print("Possible reasons:")
    print("  1. crm_ai_assistant module is not installed in this Odoo DB.")
    print("  2. The module uses a different naming convention.")
    print()
    # Also check ir.model.fields for any manual fields
    manual_fields = models.execute_kw(DB, uid, PASSWORD,
        "ir.model.fields", "search_read",
        [[["model", "=", "crm.lead"], ["state", "=", "manual"]]],
        {"fields": ["name", "field_description", "ttype"]}
    )
    if manual_fields:
        print(f"Manual/custom fields on crm.lead via ir.model.fields ({len(manual_fields)}):")
        for f in manual_fields:
            print(f"  {f['name']:40s} type={f['ttype']:15s} label={f['field_description']}")
    else:
        print("No manual fields at all on crm.lead (ir.model.fields confirms it).")
        print()
        print("ACTION NEEDED: Install the crm_ai_assistant module first, then re-run this script.")
else:
    for field_name, meta in combined.items():
        print(
            f"  Field name : {field_name}\n"
            f"  Label      : {meta.get('string', 'N/A')}\n"
            f"  Type       : {meta.get('type', 'N/A')}\n"
            f"  Required   : {meta.get('required', False)}\n"
            f"  Readonly   : {meta.get('readonly', False)}\n"
            f"  Help       : {(meta.get('help') or '')[:120] or '(none)'}\n"
        )
        print("-" * 60)

    print("\nSUMMARY — exact field names to use in the code:")
    for field_name in combined:
        print(f"  {field_name}")

print("\nDone.")
