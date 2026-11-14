#!/bin/sh
# Check three orders against a running `orderguard serve`: one allowed, one refused, one held for a human.
#
#   .venv/bin/orderguard serve                 # terminal 1 (default http://127.0.0.1:8600)
#   sh examples/http/check_order.sh [BASE_URL] # terminal 2
#
# BASE_URL defaults to $ORDERGUARD_APP_URL, then http://127.0.0.1:8600. If the server was started with ORDERGUARD_APP_TOKEN,
# export the same value here and the script sends it as "Authorization: Bearer ...". Needs only curl. Uses the server's built-in
# demo mandate (AAPL and MSFT, buy only, $10,000 per order, $20,000 per day, 5% price band, step-up above $9,500) and its
# demo prices (AAPL $222.70). Nothing is placed: /api/check-order only decides.
#
# Expected output (about a quarter of a second), exit code 0:
#
#   allow   buy 10 AAPL @ 222.70 (honest order)
#   refuse  buy 440 AAPL @ 22.30 (sized from a forged 10-for-1 split)
#           The order is worth $97,988 at the trusted price of $222.70 (440 shares), above the per-order cap of $10,000.
#           With $0 already placed today this order would bring the day's total to $97,988, above the daily cap of $20,000.
#           The limit price $22.30 is 90.0% below the trusted price $222.70; the mandate allows at most 5%.
#           The order is worth $97,988, above the $9,500 step-up threshold, so a human must approve it.
#   hold    buy 43 AAPL @ 222.70 (inside every cap, above the step-up threshold)
#           The order is worth $9,576, above the $9,500 step-up threshold, so a human must approve it.
#   OK: the three orders were allowed, refused and held as expected.
#
# Exit codes: 0 as expected, 1 a decision differed, 2 the server could not be reached or rejected the request.
set -u

BASE="${1:-${ORDERGUARD_APP_URL:-http://127.0.0.1:8600}}"
BASE="${BASE%/}"
command -v curl >/dev/null 2>&1 || { echo "error: curl was not found. Install curl, or send the same JSON with any HTTP client (see docs/QUICKSTART.md)." >&2; exit 2; }

# POST one order; prints the response body and sets STATUS. The token header is added only when ORDERGUARD_APP_TOKEN is set.
post() {
  if [ -n "${ORDERGUARD_APP_TOKEN:-}" ]; then
    RESP=$(curl -sS -m 15 -w '\n%{http_code}' "$BASE/api/check-order" -H "Authorization: Bearer $ORDERGUARD_APP_TOKEN" -H "Content-Type: application/json" -d "$1" 2>&1)
  else
    RESP=$(curl -sS -m 15 -w '\n%{http_code}' "$BASE/api/check-order" -H "Content-Type: application/json" -d "$1" 2>&1)
  fi
  CURL_RC=$?
  STATUS=$(printf '%s' "$RESP" | tail -n 1)
  BODY=$(printf '%s' "$RESP" | sed '$d')
}

check() {  # check EXPECTED QTY LIMIT NOTE
  post "{\"order\":{\"ticker\":\"AAPL\",\"side\":\"buy\",\"quantity\":$2,\"limit_price\":$3}}"
  if [ "$CURL_RC" -ne 0 ]; then
    echo "error: could not reach $BASE ($BODY)" >&2
    echo "Start the server first: .venv/bin/orderguard serve   (or pass the right address: sh $0 http://127.0.0.1:PORT)" >&2
    exit 2
  fi
  case "$STATUS" in
    200) ;;
    401) echo "error: the server wants a token. Export ORDERGUARD_APP_TOKEN with the value it was started with, then run this again." >&2; exit 2 ;;
    404) echo "error: $BASE answered 404 for /api/check-order: is that an OrderGuard server (orderguard serve)?" >&2; exit 2 ;;
    *)   echo "error: the server answered HTTP $STATUS: $BODY" >&2; exit 2 ;;
  esac
  DECISION=$(printf '%s' "$BODY" | sed -n 's/^{"decision":"\([a-z]*\)".*/\1/p')
  printf '%-7s buy %s AAPL @ %s (%s)\n' "$DECISION" "$2" "$3" "$4"
  # The reasons are plain sentences in the "reasons" array. jq is used when installed; the awk fallback keeps the script dependency-free.
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$BODY" | jq -r '.reasons[] | "          " + .'
  else
    printf '%s' "$BODY" | sed -n 's/^{"decision":"[a-z]*","reasons":\[\(.*\)\],"checks".*/\1/p' \
      | awk '{ n = split($0, a, "\",\""); for (i = 1; i <= n; i++) { t = a[i]; gsub(/^"|"$/, "", t); if (t != "") print "          " t } }'
  fi
  [ "$DECISION" = "$1" ] || { echo "UNEXPECTED: wanted $1, got ${DECISION:-nothing}" >&2; FAILED=1; }
}

FAILED=0
check allow  10  222.70 "honest order"
check refuse 440 22.30 "sized from a forged 10-for-1 split"
check hold   43  222.70 "inside every cap, above the step-up threshold"

if [ "$FAILED" -eq 0 ]; then echo "OK: the three orders were allowed, refused and held as expected."; else exit 1; fi
