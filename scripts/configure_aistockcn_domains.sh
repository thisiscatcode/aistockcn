#!/usr/bin/env bash
set -euo pipefail

site_file="/etc/nginx/sites-available/quantcn-panel"
backup_file="${site_file}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
domains="quantcn.wintrusttech.com aistockcn.com www.aistockcn.com"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run with sudo: sudo bash scripts/configure_aistockcn_domains.sh" >&2
  exit 1
fi

if [[ ! -f "${site_file}" ]]; then
  echo "Nginx site file not found: ${site_file}" >&2
  exit 1
fi

cp "${site_file}" "${backup_file}"

python3 - "${site_file}" "${domains}" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
domains = sys.argv[2]
text = path.read_text()

text = re.sub(
    r"server_name\s+quantcn\.wintrusttech\.com(?:\s+aistockcn\.com)?(?:\s+www\.aistockcn\.com)?;",
    f"server_name {domains};",
    text,
)

text = re.sub(
    r"if \(\$host = quantcn\.wintrusttech\.com\) \{",
    "if ($host ~ ^(quantcn\\.wintrusttech\\.com|aistockcn\\.com|www\\.aistockcn\\.com)$) {",
    text,
)

path.write_text(text)
PY

nginx -t
systemctl reload nginx

echo "Updated ${site_file}"
echo "Backup saved at ${backup_file}"
