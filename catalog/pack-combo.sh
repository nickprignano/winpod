#!/usr/bin/env bash
set -euo pipefail

# Validates a built Tier-1 combo QCOW2 and chunks it into a desync store + .caibx index.
# Usage: ./catalog/pack-combo.sh <combo-qcow2-path> <out-repo-dir>

COMBO_QCOW2="${1:?Usage: $0 <combo-qcow2-path> <out-repo-dir>}"
OUT_REPO="${2:?Usage: $0 <combo-qcow2-path> <out-repo-dir>}"

command -v qemu-img >/dev/null 2>&1 || { echo "ERROR: qemu-img not found"; exit 1; }
command -v desync >/dev/null 2>&1 || { echo "ERROR: desync not found"; exit 1; }
[ -f "$COMBO_QCOW2" ] || { echo "ERROR: file not found: $COMBO_QCOW2"; exit 1; }

NAME="$(basename "$COMBO_QCOW2" .qcow2)"
CHUNK_STORE="${OUT_REPO}/chunks"
INDEX_DIR="${OUT_REPO}/indexes"
mkdir -p "$CHUNK_STORE" "$INDEX_DIR"

echo "Checking QCOW2 integrity: $COMBO_QCOW2"
qemu-img check "$COMBO_QCOW2"

INDEX_FILE="${INDEX_DIR}/${NAME}.caibx"
echo "Chunking with desync -> $INDEX_FILE"
desync make -s "$CHUNK_STORE" "$INDEX_FILE" "$COMBO_QCOW2"

SHA256="$(sha256sum "$COMBO_QCOW2" | awk '{print $1}')"
SIZE_BYTES="$(stat -c%s "$COMBO_QCOW2" 2>/dev/null || wc -c < "$COMBO_QCOW2")"

echo "Packed: name=${NAME} sha256=${SHA256} bytes=${SIZE_BYTES} index=${INDEX_FILE}"
