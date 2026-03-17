#!/usr/bin/env bash
# verify-llm-endpoints.sh — Check health of all NEXUS OS LLM tiers
# Usage: ./verify-llm-endpoints.sh [--no-inference]

set -euo pipefail

NO_INFERENCE=false
[[ "${1:-}" == "--no-inference" ]] && NO_INFERENCE=true

# ANSI colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

TIMEOUT=5  # seconds for health check
INFER_TIMEOUT=30  # seconds for inference test

# Endpoint definitions: "NAME|TIER|BASE_URL|EXPECTED_MODEL"
declare -a ENDPOINTS=(
  "Coordinator|Tier 1|http://10.0.30.3:1234|qwen/qwen3.5-35b-a3b"
  "Coder|Tier 2A|http://10.0.30.2:1234|qwen/qwen2.5-coder-14b"
  "Director|Tier 2B|http://10.0.30.3:1235|qwen2.5-7b-instruct-1m"
  "Worker|Tier 3|http://10.0.20.6:11434|llama3.2:1b"
)

# Results storage
declare -a STATUS=()
declare -a MODEL_FOUND=()
declare -a INFER_RESULT=()

check_health() {
  local base_url="$1"
  local response
  response=$(curl -sf --max-time "$TIMEOUT" "${base_url}/v1/models" 2>/dev/null) || return 1
  echo "$response"
}

check_model() {
  local response="$1"
  local expected="$2"
  echo "$response" | grep -qi "$expected" && echo "yes" || echo "no"
}

run_inference() {
  local base_url="$1"
  local payload='{"model":"","messages":[{"role":"user","content":"Reply with exactly: OK"}],"max_tokens":10,"temperature":0}'

  # Get first available model id
  local model_id
  model_id=$(curl -sf --max-time "$TIMEOUT" "${base_url}/v1/models" 2>/dev/null \
    | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4) || model_id=""

  [[ -z "$model_id" ]] && echo "NO_MODEL" && return

  local body="${payload/\"model\":\"\"/\"model\":\"${model_id}\"}"
  local result
  result=$(curl -sf --max-time "$INFER_TIMEOUT" \
    -H "Content-Type: application/json" \
    -d "$body" \
    "${base_url}/v1/chat/completions" 2>/dev/null) || { echo "FAIL"; return; }

  echo "$result" | grep -o '"content":"[^"]*"' | head -1 | cut -d'"' -f4 || echo "PARSE_ERR"
}

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║         NEXUS OS — LLM Endpoint Health Check             ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════╝${RESET}"
echo ""

UP_COUNT=0
DOWN_COUNT=0

for entry in "${ENDPOINTS[@]}"; do
  IFS='|' read -r name tier base_url expected_model <<< "$entry"

  printf "  ${BOLD}%-12s${RESET} %-8s  %s  " "$name" "($tier)" "$base_url"

  response=$(check_health "$base_url") && health_ok=true || health_ok=false

  if $health_ok; then
    echo -e "${GREEN}UP${RESET}"
    STATUS+=("UP")
    ((UP_COUNT++))

    model_match=$(check_model "$response" "$expected_model")
    MODEL_FOUND+=("$model_match")

    if [[ "$model_match" == "no" ]]; then
      actual=$(echo "$response" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 || echo "unknown")
      echo -e "             ${YELLOW}⚠ Expected model '$expected_model' not found (got: $actual)${RESET}"
    else
      echo -e "             ${GREEN}✓ Model '$expected_model' confirmed${RESET}"
    fi

    if ! $NO_INFERENCE; then
      printf "             Testing inference... "
      infer_out=$(run_inference "$base_url")
      INFER_RESULT+=("$infer_out")
      if [[ "$infer_out" == "FAIL" || "$infer_out" == "NO_MODEL" || "$infer_out" == "PARSE_ERR" ]]; then
        echo -e "${RED}✗ $infer_out${RESET}"
      else
        echo -e "${GREEN}✓ Response: '$infer_out'${RESET}"
      fi
    else
      INFER_RESULT+=("SKIPPED")
    fi
  else
    echo -e "${RED}DOWN${RESET}"
    STATUS+=("DOWN")
    MODEL_FOUND+=("N/A")
    INFER_RESULT+=("N/A")
    ((DOWN_COUNT++))
  fi
  echo ""
done

# Summary table
echo -e "${BOLD}${CYAN}┌──────────────┬──────────┬────────┬───────────────────────────┬──────────────────┐${RESET}"
printf "${BOLD}${CYAN}│${RESET} %-12s ${BOLD}${CYAN}│${RESET} %-8s ${BOLD}${CYAN}│${RESET} %-6s ${BOLD}${CYAN}│${RESET} %-25s ${BOLD}${CYAN}│${RESET} %-16s ${BOLD}${CYAN}│${RESET}\n" \
  "Endpoint" "Tier" "Status" "Expected Model" "Inference"
echo -e "${BOLD}${CYAN}├──────────────┼──────────┼────────┼───────────────────────────┼──────────────────┤${RESET}"

for i in "${!ENDPOINTS[@]}"; do
  IFS='|' read -r name tier base_url expected_model <<< "${ENDPOINTS[$i]}"
  st="${STATUS[$i]}"
  mf="${MODEL_FOUND[$i]}"
  ir="${INFER_RESULT[$i]}"

  if [[ "$st" == "UP" ]]; then
    st_colored="${GREEN}UP    ${RESET}"
  else
    st_colored="${RED}DOWN  ${RESET}"
  fi

  # Truncate inference result for table
  ir_short="${ir:0:16}"

  printf "${BOLD}${CYAN}│${RESET} %-12s ${BOLD}${CYAN}│${RESET} %-8s ${BOLD}${CYAN}│${RESET} %b${BOLD}${CYAN}│${RESET} %-25s ${BOLD}${CYAN}│${RESET} %-16s ${BOLD}${CYAN}│${RESET}\n" \
    "$name" "$tier" "$st_colored" "${expected_model:0:25}" "$ir_short"
done

echo -e "${BOLD}${CYAN}└──────────────┴──────────┴────────┴───────────────────────────┴──────────────────┘${RESET}"
echo ""
echo -e "  Summary: ${GREEN}${UP_COUNT} UP${RESET}  /  ${RED}${DOWN_COUNT} DOWN${RESET}  (of ${#ENDPOINTS[@]} endpoints)"
echo ""

if [[ $DOWN_COUNT -gt 0 ]]; then
  echo -e "  ${YELLOW}Troubleshooting tips:${RESET}"
  for i in "${!ENDPOINTS[@]}"; do
    if [[ "${STATUS[$i]}" == "DOWN" ]]; then
      IFS='|' read -r name tier base_url expected_model <<< "${ENDPOINTS[$i]}"
      case "$name" in
        Coordinator)
          echo -e "  • ${BOLD}Coordinator${RESET}: Start LM Studio on ThinkStation (10.0.30.3), load qwen3.5-35b-a3b, enable server on port 1234. Thinking=OFF, JIT=OFF."
          ;;
        Coder)
          echo -e "  • ${BOLD}Coder${RESET}: Start LM Studio on ThinkPad (10.0.30.2), load qwen2.5-coder-14b, enable server on port 1234. JIT=OFF."
          ;;
        Director)
          echo -e "  • ${BOLD}Director${RESET}: In LM Studio on ThinkStation, load qwen2.5-7b-instruct-1m as a second model and set server port to 1235. JIT=OFF."
          ;;
        Worker)
          echo -e "  • ${BOLD}Worker${RESET}: On nexus-ai2 (10.0.20.6) check: systemctl status ollama && ollama list. NFS must be mounted (/mnt/nexus-nas). See /opt/nexus/docs/LLM_HIERARCHY.md for details."
          ;;
      esac
    fi
  done
  echo ""
fi

exit $DOWN_COUNT
