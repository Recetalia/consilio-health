#!/usr/bin/env bash
#
# End-to-end API contract tests for Consilio.
# Validates every field the iOS app depends on.
#
# Usage: ./scripts/e2e-test.sh [BASE_URL] [API_KEY]
#   API_KEY is optional — if provided, sends X-API-Key header.

set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
API_KEY="${2:-}"
PASSED=0
FAILED=0

fail() { echo "  FAIL: $1"; FAILED=$((FAILED + 1)); }
pass() { echo "  PASS: $1"; PASSED=$((PASSED + 1)); }

assert_eq() {
    local desc="$1" actual="$2" expected="$3"
    if [ "$actual" = "$expected" ]; then pass "$desc"
    else fail "$desc (expected '$expected', got '$actual')"; fi
}

assert_not_empty() {
    local desc="$1" value="$2"
    if [ -n "$value" ] && [ "$value" != "null" ]; then pass "$desc"
    else fail "$desc (got empty or null)"; fi
}

assert_status() {
    local desc="$1" actual="$2" expected="$3"
    if [ "$actual" = "$expected" ]; then pass "$desc"
    else fail "$desc (expected HTTP $expected, got HTTP $actual)"; fi
}

# Build curl auth args
AUTH_ARGS=()
if [ -n "$API_KEY" ]; then
    AUTH_ARGS=(-H "X-API-Key: $API_KEY")
fi

# --- Wait for API ---

echo "Waiting for API at $BASE_URL..."
for i in $(seq 1 60); do
    if curl -sf "$BASE_URL/health" > /dev/null 2>&1; then
        echo "API ready."
        break
    fi
    if [ "$i" -eq 60 ]; then echo "ERROR: API not healthy."; exit 1; fi
    sleep 2
done

# ============================================
# 1. Health endpoints (no auth required)
# ============================================

echo ""
echo "=== GET /health ==="
HEALTH=$(curl -sf "$BASE_URL/health")
assert_eq "status" "$(echo "$HEALTH" | jq -r '.status')" "ok"
assert_not_empty "version" "$(echo "$HEALTH" | jq -r '.version')"

echo ""
echo "=== GET /health/data ==="
DATA_HEALTH=$(curl -sf "$BASE_URL/health/data")
assert_eq "status" "$(echo "$DATA_HEALTH" | jq -r '.status')" "ready"
assert_eq "ddinter" "$(echo "$DATA_HEALTH" | jq -r '.ddinter')" "connected"

# ============================================
# 3. POST /interactions — contract validation
# ============================================

echo ""
echo "=== POST /interactions (known interaction) ==="
INTERACTIONS=$(curl -sf -X POST "$BASE_URL/interactions" \
    -H "Content-Type: application/json" \
    ${AUTH_ARGS[@]+"${AUTH_ARGS[@]}"} \
    -d '{"drugs": ["ibuprofen", "warfarin"]}')

assert_eq "safe" "$(echo "$INTERACTIONS" | jq -r '.safe')" "false"
INTER_COUNT=$(echo "$INTERACTIONS" | jq '.interactions | length')
if [ "$INTER_COUNT" -gt 0 ]; then pass "interactions array not empty ($INTER_COUNT)"
else fail "interactions array is empty"; fi
# Verify all InteractionResult fields (iOS InteractionResult.swift CodingKeys)
assert_not_empty "drug_a" "$(echo "$INTERACTIONS" | jq -r '.interactions[0].drug_a')"
assert_not_empty "drug_b" "$(echo "$INTERACTIONS" | jq -r '.interactions[0].drug_b')"
assert_not_empty "severity" "$(echo "$INTERACTIONS" | jq -r '.interactions[0].severity')"
assert_not_empty "source" "$(echo "$INTERACTIONS" | jq -r '.interactions[0].source')"
assert_not_empty "description" "$(echo "$INTERACTIONS" | jq -r '.interactions[0].description')"
assert_not_empty "management" "$(echo "$INTERACTIONS" | jq -r '.interactions[0].management')"
assert_eq "coverage_summary present" "$(echo "$INTERACTIONS" | jq '.coverage_summary.ddinter != null')" "true"

echo ""
echo "=== POST /interactions (safe pair) ==="
SAFE=$(curl -sf -X POST "$BASE_URL/interactions" \
    -H "Content-Type: application/json" \
    ${AUTH_ARGS[@]+"${AUTH_ARGS[@]}"} \
    -d '{"drugs": ["acetaminophen", "atorvastatin"]}')
assert_eq "safe" "$(echo "$SAFE" | jq -r '.safe')" "true"
assert_eq "no interactions" "$(echo "$SAFE" | jq '.interactions | length')" "0"

echo ""
echo "=== POST /interactions (too few drugs → 422) ==="
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/interactions" \
    -H "Content-Type: application/json" \
    ${AUTH_ARGS[@]+"${AUTH_ARGS[@]}"} \
    -d '{"drugs": ["only_one"]}')
assert_status "single drug rejected" "$STATUS" "422"

# ============================================
# 4. Auth tests (only when API_KEY is set)
# ============================================

if [ -n "$API_KEY" ]; then
    echo ""
    echo "=== Auth: no key → 401 ==="
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/interactions" \
        -H "Content-Type: application/json" \
        -d '{"drugs": ["warfarin", "ibuprofen"]}')
    assert_status "no key rejected" "$STATUS" "401"

    echo ""
    echo "=== Auth: wrong key → 401 ==="
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/interactions" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: wrong-key-12345" \
        -d '{"drugs": ["warfarin", "ibuprofen"]}')
    assert_status "wrong key rejected" "$STATUS" "401"

    echo ""
    echo "=== Auth: health endpoints need no key ==="
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health")
    assert_status "/health no auth needed" "$STATUS" "200"
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/health/data")
    assert_status "/health/data no auth needed" "$STATUS" "200"
fi

# --- Summary ---

echo ""
echo "================================"
echo "Results: $PASSED passed, $FAILED failed"
echo "================================"

[ "$FAILED" -eq 0 ] || exit 1
