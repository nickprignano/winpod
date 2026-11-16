#!/usr/bin/env bash
set -euo pipefail

# Required mounts:
#   /images/base   (RO) - contains win11-base.qcow2 (referenced by combo backing chain)
#   /images/combo  (RO) - contains the selected combo-*.qcow2
#   /state         (RW) - per-persona writable state (local.qcow2, tpm/, OVMF_VARS.fd, sockets)

COMBO_QCOW2="${COMBO_QCOW2:-/images/combo/combo.qcow2}"
LOCAL_QCOW2="${LOCAL_QCOW2:-/state/local.qcow2}"
USER_IMG="${USER_IMG:-/state/user-data.qcow2}"
RAM_MB="${RAM_MB:-8192}"
CPUS="${CPUS:-4}"
RDP_PORT="${RDP_PORT:-3389}"

[ -e /dev/kvm ] || { echo "ERROR: /dev/kvm not found"; exit 1; }
[ -f "$COMBO_QCOW2" ] || { echo "ERROR: missing $COMBO_QCOW2"; exit 1; }

mkdir -p /state/tpm

# 1. Create ephemeral Tier-2 OS overlay backed by Tier-1 combo if missing
if [ ! -f "$LOCAL_QCOW2" ]; then
  echo "Creating Tier-2 overlay $LOCAL_QCOW2 -> $COMBO_QCOW2"
  qemu-img create -f qcow2 -F qcow2 -b "$COMBO_QCOW2" "$LOCAL_QCOW2"
fi

# 2. Initialize writable UEFI vars (Secure Boot) per persona
OVMF_CODE=$(ls /usr/share/OVMF/OVMF_CODE_4M*.fd /usr/share/OVMF/OVMF_CODE.fd 2>/dev/null | head -n1)
OVMF_VARS_TMPL=$(ls /usr/share/OVMF/OVMF_VARS_4M*.fd /usr/share/OVMF/OVMF_VARS.fd 2>/dev/null | head -n1)
if [ ! -f /state/OVMF_VARS.fd ]; then
  cp "$OVMF_VARS_TMPL" /state/OVMF_VARS.fd
fi

# 3. Start per-persona TPM 2.0 (swtpm)
rm -f /state/swtpm.sock
swtpm socket --daemon \
  --tpmstate dir=/state/tpm \
  --ctrl type=unixio,path=/state/swtpm.sock \
  --tpm2

# 4. Graceful ACPI shutdown on SIGTERM (docker stop)
QMP_SOCK="/state/qmp.sock"
shutdown_vm() {
  if [ -S "$QMP_SOCK" ]; then
    echo "Sending ACPI powerdown via QMP..."
    printf '{"execute":"qmp_capabilities"}\n{"execute":"system_powerdown"}\n' \
      | socat - UNIX-CONNECT:"$QMP_SOCK" >/dev/null 2>&1 || true
    wait "$QEMU_PID" 2>/dev/null || true
  fi
  exit 0
}
trap shutdown_vm SIGTERM SIGINT

# 5. Optional Tier-3 persistent user data disk
EXTRA_DISKS=()
if [ -f "$USER_IMG" ]; then
  EXTRA_DISKS+=(-drive "file=$USER_IMG,if=none,id=userdata,format=qcow2,discard=unmap" \
                -device "virtio-blk-pci,drive=userdata")
fi

# 6. Launch QEMU/KVM with Hyper-V enlightenments + QMP + Guest Agent
qemu-system-x86_64 \
  -name "winpod" \
  -machine q35,accel=kvm,kernel_irqchip=on \
  -cpu host,hv_relaxed,hv_spinlocks=0x1fff,hv_vapic,hv_time,hv_vpindex,hv_synic,hv_stimer,hv_reset \
  -smp "$CPUS" \
  -m "$RAM_MB" \
  -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE" \
  -drive "if=pflash,format=raw,file=/state/OVMF_VARS.fd" \
  -chardev "socket,id=chrtpm,path=/state/swtpm.sock" \
  -tpmdev "emulator,id=tpm0,chardev=chrtpm" \
  -device "tpm-crb,tpmdev=tpm0" \
  -drive "file=$LOCAL_QCOW2,if=none,id=osdisk,format=qcow2,discard=unmap" \
  -device "virtio-blk-pci,drive=osdisk,bootindex=1" \
  "${EXTRA_DISKS[@]}" \
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:${RDP_PORT}-:3389" \
  -device "virtio-net-pci,netdev=net0" \
  -chardev "socket,id=qmp0,path=${QMP_SOCK},server=on,wait=off" \
  -mon "chardev=qmp0,mode=control" \
  -device "virtio-serial-pci" \
  -chardev "socket,path=/state/qga.sock,server=on,wait=off,id=qga0" \
  -device "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0" \
  -display none \
  -usb -device usb-tablet &

QEMU_PID=$!
wait "$QEMU_PID"
