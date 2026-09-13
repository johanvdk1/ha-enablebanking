# Enable Banking for Home Assistant — Setup Guide

This guide documents the full setup process for the Enable Banking custom
integration, which exposes bank account balances and transaction totals as
Home Assistant sensors via the PSD2 open banking API.

---

## Prerequisites

- Home Assistant OS (HAOS)
- HACS installed on HA
- SSH access to HA (Terminal & SSH add-on)
- A Mac or Linux machine for the initial setup steps

---

## Step 1 — Create an Enable Banking Account

1. Go to [enablebanking.com](https://enablebanking.com) and sign up
   (free for personal use — no password, magic-link login).

---

## Step 2 — Generate a Private Key and Certificate

Run these commands **on your Home Assistant machine** via SSH:

```bash
ssh hassio@YOUR_HA_IP
mkdir -p /homeassistant/enablebanking
cd /homeassistant/enablebanking
openssl genrsa -out private.key 2048
openssl req -new -x509 -key private.key -out certificate.pem \
        -days 3650 -subj "/CN=homeassistant"
cat certificate.pem      # copy this output — you need it in Step 3
exit
```

Copy the `private.key` to your Mac for use by the auth script:

```bash
ssh hassio@YOUR_HA_IP "cat /homeassistant/enablebanking/private.key" \
    > ~/enablebanking/private.key
```

---

## Step 3 — Register an Application on Enable Banking

1. Log in to [enablebanking.com](https://enablebanking.com)
2. Go to **API applications → Create new application**
3. Fill in:
   - **Name:** Home Assistant
   - **Environment:** PRODUCTION
   - **Certificate:** paste the full contents of `certificate.pem`
   - **Redirect URL:** `https://localhost/local`
   - **Privacy policy URL:** `https://localhost/privacy`
   - **Terms of service URL:** `https://localhost/terms`
   - **Data protection email:** your email address
4. Submit — you will receive an **Application ID** (UUID).  
   Save this; you will need it in Step 6.

---

## Step 4 — Set Up the Auth Script on Your Mac

### 4a — Create a Python virtual environment

```bash
python3 -m venv ~/enablebanking
source ~/enablebanking/bin/activate
pip install cryptography PyJWT requests
```

### 4b — Copy the auth script

Copy `auth_bank.py` (from this repo) to `~/enablebanking/auth_bank.py`.

Edit the **CONFIG** block at the top of `auth_bank.py`:

```python
APP_ID           = "YOUR_APP_ID"          # from Step 3
PRIVATE_KEY_PATH = "private.key"          # already in ~/enablebanking/
SESSIONS_PATH    = "sessions.json"
BANK_NAME        = "Argenta"              # change per bank
BANK_COUNTRY     = "BE"
```

---

## Step 5 — Link Your Bank Accounts

Run the auth script **once per bank account**:

```bash
source ~/enablebanking/bin/activate   # if not already active
cd ~/enablebanking
python3 auth_bank.py
```

1. The script prints a URL — open it in your browser.
2. Log in to your bank and authorize access (you will need your banking
   app for the authentication step).
3. You will be redirected to `https://localhost/local?code=…`  
   The browser shows an error — **that is expected**.
4. Copy the full URL from the address bar and paste it at the `>` prompt.
5. The script saves the session to `sessions.json`.

Repeat for each bank by changing `BANK_NAME` at the top of `auth_bank.py`.

### Supported Belgian banks (via Enable Banking)

Argenta · Belfius · ING · KBC / CBC · Crelan

### Copy sessions.json to HA

```bash
ssh hassio@YOUR_HA_IP \
    "cat > /homeassistant/enablebanking/sessions.json" \
    < ~/enablebanking/sessions.json
```

---

## Step 6 — Install the Integration via HACS

1. Open HACS in Home Assistant
2. **Integrations → three-dot menu → Custom repositories**
3. Add `https://github.com/johanvdk1/ha-enablebanking` — category **Integration**
4. Install **Enable Banking**
5. Restart Home Assistant

---

## Step 7 — Configure configuration.yaml

```yaml
enablebanking:
  transaction_interval: 720   # minutes between transaction fetches (≤ 2/day for Argenta)
  balance_interval: 1440      # minutes between balance fetches (1/day for Argenta)
  sensors:
    - name: "Luminus This Year"
      aggregate: sum
      direction: DBIT
      period:
        from: >
          {{ (now().replace(month=2, day=1) if now().month >= 2
              else now().replace(year=now().year - 1, month=2, day=1))
              .strftime('%Y-%m-%d') }}
      match:
        - field: remittance
          value: "luminus voorschot"
```

### Sensor options

| Field | Description | Values |
|-------|-------------|--------|
| `name` | Sensor name in HA | Any string |
| `aggregate` | How to aggregate matching transactions | `sum`, `avg`, `min`, `max`, `count` |
| `direction` | Transaction direction | `DBIT` (outgoing), `CRDT` (incoming) |
| `period.from` | Start date (ISO or Jinja template) | e.g. `2026-01-01` or Jinja |
| `period.to` | End date (ISO or Jinja template) | optional |
| `match` | List of field/value filters | see below |

### Match fields

| `field` | Database column |
|---------|----------------|
| `creditor` | creditor name |
| `debtor` | debtor name |
| `remittance` | remittance information |
| `currency` | currency code |
| `reference` | entry reference |

### Match modes (optional, default: `contains`)

`contains` · `equals` · `starts_with` · `ends_with`

---

## Step 8 — Add the Integration in HA

1. **Settings → Integrations → Add Integration → Enable Banking**
2. Enter your **Application ID** from Step 3
3. Submit and restart HA

Sensors appear immediately (reading from the local SQLite database).
Values populate after the first successful scheduled API fetch.

---

## Rate Limits (Argenta)

Argenta enforces strict PSD2 rate limits per account per endpoint:

- **Transactions:** ~2 requests per 24-hour rolling window
- **Balances:** similar, but appears more lenient in practice

The defaults (`transaction_interval: 720`, `balance_interval: 1440`) keep
usage within these limits under normal operation. The integration does **not**
fetch on HA restart to preserve your daily quota.

---

## Re-authorizing Bank Access (every 90 days)

Sessions expire after 90 days. When you see a **401 error** in the HA logs
for the enablebanking integration, re-run the auth script:

```bash
source ~/enablebanking/bin/activate
cd ~/enablebanking
python3 auth_bank.py          # set BANK_NAME to the affected bank
```

Then copy the updated `sessions.json` to HA:

```bash
ssh hassio@YOUR_HA_IP \
    "cat > /homeassistant/enablebanking/sessions.json" \
    < ~/enablebanking/sessions.json
```

No HA restart is needed — the integration reads `sessions.json` on every
fetch cycle.

---

## Checking the Local Database

Transactions are stored in `/config/enablebanking/transactions.db` (SQLite).
You can inspect it from your Mac:

```bash
ssh hassio@YOUR_HA_IP \
    "sqlite3 /homeassistant/enablebanking/transactions.db \
     'SELECT iban, amount, last_updated FROM balances;'"

ssh hassio@YOUR_HA_IP \
    "sqlite3 /homeassistant/enablebanking/transactions.db \
     'SELECT booking_date, creditor_name, remittance_information, amount \
      FROM transactions ORDER BY booking_date DESC LIMIT 20;'"
```

Or install the **SQLite Web** add-on in HACS to browse it from the HA UI.
