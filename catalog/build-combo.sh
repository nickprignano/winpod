#!/usr/bin/env bash
set -euo pipefail

# Creates a Tier-1 combo overlay backed by win11-base.qcow2
# Usage: ./catalog/build-combo.sh <combo-name> <path-to-win11-base.qcow2>

COMBO_NAME="${1:?Usage: $0 <combo-name> <base-qcow2-path>}"
BASE_QCOW2="${2:?Usage: $0 <combo-name> <base-qcow2-path>}"
OUT_DIR="${OUT_DIR:-/var/lib/winpod/combos/${COMBO_NAME}}"

[ -f "$BASE_QCOW2" ] || { echo "ERROR: base image not found: $BASE_QCOW2"; exit 1; }

mkdir -p "$OUT_DIR"
COMBO_QCOW2="${OUT_DIR}/${COMBO_NAME}.qcow2"

echo "Creating Tier-1 combo overlay: $COMBO_QCOW2 -> $BASE_QCOW2"
qemu-img create -f qcow2 -F qcow2 -b "$BASE_QCOW2" "$COMBO_QCOW2"

echo "Done. Boot $COMBO_QCOW2 in build mode to install apps, run 'sdelete -z', shut down, and chunk with desync."
