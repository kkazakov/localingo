#!/usr/bin/env bash
set -e

declare -A MODEL_MAP
declare -a MODEL_LIST

add_model() {
  local model_id="$1"
  local model_alias="$2"
  local vram_req="$3"
  local display_name="$model_alias ($vram_req)"
  MODEL_MAP["$display_name"]="$model_id|$model_alias"
  MODEL_LIST+=("$display_name")
}

add_model "google/translategemma-12b-it" "translategemma-12b-Q8" "24 GB VRAM"
add_model "google/translategemma-12b-it" "translategemma-12b-Q4" "12 GB VRAM"
add_model "google/translategemma-12b-it" "translategemma-12b-Q2" "7 GB VRAM"
add_model "google/translategemma-27b-it" "translategemma-27b-Q8" "54 GB VRAM"
add_model "google/translategemma-27b-it" "translategemma-27b-Q4" "28 GB VRAM"
add_model "google/translategemma-27b-it" "translategemma-27b-Q2" "16 GB VRAM"

ENV_FILE=".env"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found. Copy .env.example to .env and set HF_TOKEN."
  exit 1
fi

source "$ENV_FILE"

if [ -z "$HF_TOKEN" ]; then
  echo "Error: HF_TOKEN not set in $ENV_FILE"
  exit 1
fi

if [ -t 0 ]; then
  stty sane 2>/dev/null || true
fi

echo "Select a TranslateGemma model:"
echo ""

for i in $(seq 0 $((${#MODEL_LIST[@]} - 1))); do
  display_name="${MODEL_LIST[$i]}"
  printf "  [%d] %s\n" $((i + 1)) "$display_name"
done

echo ""
read -p "Enter selection (1-${#MODEL_LIST[@]}): " choice

if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#MODEL_LIST[@]}" ]; then
  echo "Invalid selection."
  exit 1
fi

display_name="${MODEL_LIST[$((choice - 1))]}"
selection="${MODEL_MAP[$display_name]}"
model_id=$(echo "$selection" | cut -d'|' -f1)
model_alias=$(echo "$selection" | cut -d'|' -f2)

echo ""
echo "Selected: $model_alias"
echo "Model ID: $model_id"
echo ""

if grep -q "^MODEL_ID=" "$ENV_FILE"; then
  sed -i "s|^MODEL_ID=.*|MODEL_ID=$model_id|" "$ENV_FILE"
else
  echo "MODEL_ID=$model_id" >> "$ENV_FILE"
fi

if grep -q "^MODEL_ALIAS=" "$ENV_FILE"; then
  sed -i "s|^MODEL_ALIAS=.*|MODEL_ALIAS=$model_alias|" "$ENV_FILE"
else
  echo "MODEL_ALIAS=$model_alias" >> "$ENV_FILE"
fi

echo "Done! Updated $ENV_FILE with:"
echo "  MODEL_ID=$model_id"
echo "  MODEL_ALIAS=$model_alias"
echo ""
echo "Restart the service to use the new model:"
echo "  docker compose up -d --build translate-backend"
