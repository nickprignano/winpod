# winpod

**Portable, layered Windows 11 personas on Linux laptops.**

Inspired by Citrix XenClient / OpenXT, **winpod** runs isolated, centrally managed Windows 11 environments on a thin Linux host using KVM, 3-tier QCOW2 backing chains, per-persona virtual TPM 2.0 (`swtpm`), and chunked delta sync (`desync`).

> **Disclaimer:** Not affiliated with Microsoft or Citrix. No Windows binaries, ISOs, or disk images are distributed in this repository. Users and organizations are solely responsible for supplying their own Windows media and complying with Microsoft licensing terms.

---

## Why winpod?

- **No bare-metal driver hell:** Linux handles laptop Wi-Fi, sleep/wake, audio, Bluetooth, Thunderbolt, and battery.
- **3-Tier QCOW2 storage:**
  1. `win11-base.qcow2` *(Read-Only)* — Shared Windows 11 base image.
  2. `combo-<name>-<ver>.qcow2` *(Read-Only, backed by base)* — App-combo layer from your catalog.
  3. `local-<profile>.qcow2` *(Read-Write, backed by combo)* — Ephemeral OS writes; reset cleanly on combo updates.
  4. `user-data.qcow2` *(Read-Write, persistent)* — User files/profile + `swtpm` state that survive OS/app updates.
- **Fast delta updates:** Package combo layers with `desync` so laptops only pull changed chunks from S3/R2/Blob.
- **Full QMP & Guest Agent control:** Clean ACPI shutdowns, VM hibernation to disk (`0 GB` RAM when inactive), and clock resync on laptop wake.

---

## Quickstart (Single-Persona Runtime)

### Prerequisites
- x86_64 Linux host with `/dev/kvm` enabled
- Docker + Docker Compose
- `qemu-utils` (for creating/inspecting QCOW2 overlays)

### 1. Build the runtime image
```bash
docker build -t winpod-runtime ./runtime
```

### 2. Prepare your base & combo images
Build or place your Sysprepped `win11-base.qcow2` (with VirtIO storage/network drivers and `qemu-guest-agent` installed) in `/var/lib/winpod/base/`, then create a combo overlay:
```bash
./catalog/build-combo.sh dev-stack-v1 /var/lib/winpod/base/win11-base.qcow2
```

### 3. Boot a persona
```bash
cp runtime/docker-compose.example.yml docker-compose.yml
docker compose up -d
```

Connect over loopback RDP:
```bash
xfreerdp /v:127.0.0.1:3389 /u:User /dynamic-resolution /multimon /sound /clipboard
```

---

## Roadmap

- [x] **v0.1 (`runtime/`):** Minimal QEMU/KVM container, 3-tier QCOW2 boot, `swtpm`, QMP/QGA sockets.
- [ ] **v0.2 (`catalog/`):** Automated `win11-base` builder + `desync` chunk publisher + signed `catalog.json`.
- [ ] **v0.3 (`sync/`):** Background `desync` puller + atomic Tier-1 swapper.
- [ ] **v0.4 (`switcher/`):** Wayland/`cage` kiosk UI, hotkey switching, and `systemd-sleep` QGA clock-resync hooks.

## License

Apache-2.0 (see [LICENSE](LICENSE)).
