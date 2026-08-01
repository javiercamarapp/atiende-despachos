#!/usr/bin/env python3
"""Add env vars to integration adapters - v3 with proper multi-line import handling."""
import re
import os

BASE = "/Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise"

all_envs = {
    "bancos/bbva.py": "BBVA_API_KEY",
    "bancos/banorte.py": "BANORTE_API_KEY",
    "bancos/santander.py": "SANTANDER_API_KEY",
    "bancos/hsbc.py": "HSBC_API_KEY",
    "bancos/banamex.py": "BANAMEX_API_KEY",
    "bancos/scotiabank.py": "SCOTIABANK_API_KEY",
    "bancos/inbursa.py": "INBURSA_API_KEY",
    "bancos/afirme.py": "AFIRME_API_KEY",
    "erp/contpaqi_web.py": "CONTPAQI_WEB_API_KEY",
    "erp/contpaqi_desktop.py": "CONTPAQI_DESKTOP_LICENSE",
    "erp/contpaqi_one.py": "CONTPAQI_ONE_API_KEY",
    "erp/aspel_cloud.py": "ASPEL_CLOUD_API_KEY",
    "erp/quickbooks.py": "QUICKBOOKS_CLIENT_ID",
    "erp/quickbooks_desktop.py": "QUICKBOOKS_DESKTOP_LICENSE",
    "erp/xero.py": "XERO_CLIENT_ID",
    "erp/peak.py": "PEAK_API_KEY",
    "erp/multileg.py": "MULTILEG_API_KEY",
    "erp/euroweb.py": "EUROWEB_API_KEY",
    "erp/absis.py": "ABSIS_API_KEY",
    "erp/factor_d.py": "FACTOR_D_API_KEY",
    "erp/taxko.py": "TAXKO_API_KEY",
    "erp/facturadirecta.py": "FACTURADIRECTA_API_KEY",
    "sat/ecodex.py": "ECODEX_API_KEY",
    "sat/finkok.py": "FINKOK_API_KEY",
    "sat/sat_portal.py": "SAT_PORTAL_TOKEN",
    "sat_direct/sat_direct_adapter.py": "SAT_DIRECT_FIEL_KEY",
    "comunicacion/mailgun_adapter.py": "MAILGUN_API_KEY",
    "comunicacion/vonage_adapter.py": "VONAGE_API_KEY",
    "comunicacion/aws_ses_adapter.py": "AWS_SES_ACCESS_KEY",
    "comunicacion/messagebird_adapter.py": "MESSAGEBIRD_API_KEY",
    "storage/google_drive_adapter.py": "GOOGLE_DRIVE_CREDENTIALS",
    "storage/onedrive_adapter.py": "ONEDRIVE_CLIENT_ID",
    "storage/s3_adapter.py": "AWS_S3_ACCESS_KEY",
    "storage/dropbox_adapter.py": "DROPBOX_ACCESS_TOKEN",
    "storage/box_adapter.py": "BOX_ACCESS_TOKEN",
    "storage/gcs_adapter.py": "GCS_PROJECT_ID",
    "firmas/docusign_adapter.py": "DOCUSIGN_API_KEY",
    "firmas/adobe_sign_adapter.py": "ADOBE_SIGN_API_KEY",
    "firmas/fiel_adapter.py": "SAT_FIEL_CERT_PATH",
    "crm/hubspot_adapter.py": "HUBSPOT_API_KEY",
    "crm/pipedrive_adapter.py": "PIPEDRIVE_API_KEY",
    "crm/salesforce_adapter.py": "SALESFORCE_CLIENT_ID",
    "crm/zoho_crm_adapter.py": "ZOHO_CRM_CLIENT_ID",
    "monitoreo/sentry_adapter.py": "SENTRY_DSN",
    "monitoreo/datadog_adapter.py": "DATADOG_API_KEY",
    "monitoreo/newrelic_adapter.py": "NEW_RELIC_LICENSE_KEY",
    "monitoreo/logrocket_adapter.py": "LOGROCKET_APP_ID",
    "ai/openai_adapter.py": "OPENAI_API_KEY",
    "ai/anthropic_adapter.py": "ANTHROPIC_API_KEY",
    "ai/vertex_adapter.py": "GOOGLE_CLOUD_PROJECT",
    "analytics/google_analytics_adapter.py": "GA_MEASUREMENT_ID",
    "analytics/mixpanel_adapter.py": "MIXPANEL_TOKEN",
    "analytics/amplitude_adapter.py": "AMPLITUDE_API_KEY",
    "pagos/conekta_adapter.py": "CONEKTA_API_KEY",
    "pagos/paypal_adapter.py": "PAYPAL_CLIENT_ID",
    "pagos/kushki_adapter.py": "KUSHKI_PUBLIC_KEY",
    "pagos/mercadopago_adapter.py": "MERCADOPAGO_ACCESS_TOKEN",
    "pagos/paypal_mexico_adapter.py": "PAYPAL_MX_CLIENT_ID",
}

def find_import_insert_pos(lines):
    """Find the correct position to insert 'import os' - after all import blocks."""
    pos = 0
    in_docstring = False
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Skip coding declaration
        if stripped.startswith("# -*- coding"):
            pos = i + 1
            continue
        
        # Handle docstrings
        if '"""' in stripped or "'''" in stripped:
            quote = '"""' if '"""' in stripped else "'''"
            count = stripped.count(quote)
            if count == 2:
                pos = i + 1
                continue
            elif count == 1:
                in_docstring = not in_docstring
                if not in_docstring:
                    pos = i + 1
                continue
        
        if in_docstring:
            continue
        
        # Skip comments and blank lines
        if stripped.startswith("#") or stripped == "":
            pos = i + 1
            continue
        
        # If we hit a class or def, we've gone too far
        if stripped.startswith("class ") or stripped.startswith("def "):
            break
        
        # If it's an import statement (single or multi-line)
        if stripped.startswith("from ") or stripped.startswith("import "):
            # Check if it's a multi-line import
            if "(" in stripped and ")" not in stripped:
                # Multi-line import - find the closing paren
                depth = 0
                for j in range(i, len(lines)):
                    depth += lines[j].count("(") - lines[j].count(")")
                    if depth <= 0:
                        pos = j + 1
                        break
            else:
                pos = i + 1
    
    return pos

def add_env_var_to_file(filepath, env_var):
    """Add env var to adapter file."""
    with open(filepath, "r") as f:
        content = f.read()
    
    if env_var in content:
        return False, "already has env var"
    
    lines = content.split("\n")
    
    # Add import os if not present
    if "import os" not in content:
        insert_pos = find_import_insert_pos(lines)
        lines.insert(insert_pos, "import os")
        content = "\n".join(lines)
    
    # Add env var to config
    if "BankConfig(" in content:
        pattern = r'(account_number="[^"]*")'
        match = re.search(pattern, content)
        if match:
            old = match.group(0)
            new = f'{old},\n            api_key=os.environ.get("{env_var}", "")'
            content = content.replace(old, new, 1)
    
    elif "ERPConfig(" in content:
        pattern = r'(company_id="[^"]*")'
        match = re.search(pattern, content)
        if match:
            old = match.group(0)
            new = f'{old},\n            api_key=os.environ.get("{env_var}", "")'
            content = content.replace(old, new, 1)
    
    elif 'setdefault("password"' in content:
        old = 'config.setdefault("password", "********")\n        super().__init__'
        new = f'config.setdefault("password", "********")\n        config.setdefault("api_key", os.environ.get("{env_var}", ""))\n        super().__init__'
        if old in content:
            content = content.replace(old, new, 1)
    
    else:
        pattern = r'(def __init__\(self.*?\).*?\n.*?config = config or \w+\()([^)]*)\)'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            old = match.group(0)
            new_config = match.group(1) + match.group(2)
            if "api_key" not in new_config:
                if new_config.endswith("("):
                    new_config += f'\n            api_key=os.environ.get("{env_var}", ""),\n        )'
                else:
                    new_config += f',\n            api_key=os.environ.get("{env_var}", ""),\n        )'
                content = content.replace(old, new_config, 1)
    
    with open(filepath, "w") as f:
        f.write(content)
    
    return True, "added"

fixed = 0
skipped = 0
errors = 0

for rel_path, env_var in all_envs.items():
    filepath = os.path.join(BASE, "b2b_ai/integrations", rel_path)
    
    if not os.path.exists(filepath):
        skipped += 1
        continue
    
    try:
        result, msg = add_env_var_to_file(filepath, env_var)
        if result:
            fixed += 1
            print(f"  OK   {rel_path}: {env_var}")
        else:
            skipped += 1
    except Exception as e:
        errors += 1
        print(f"  ERR  {rel_path}: {e}")

print(f"\nFixed: {fixed}, Skipped: {skipped}, Errors: {errors}")

# Verify all files compile
import py_compile
broken = []
for root, dirs, files in os.walk(os.path.join(BASE, "b2b_ai/integrations")):
    for f in files:
        if f.endswith(".py"):
            fp = os.path.join(root, f)
            try:
                py_compile.compile(fp, doraise=True)
            except:
                broken.append(os.path.relpath(fp, BASE))

if broken:
    print(f"\nWARNING: {len(broken)} files have syntax errors:")
    for b in broken:
        print(f"  {b}")
else:
    print("\nAll files compile successfully!")
