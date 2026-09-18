#!/usr/bin/env bash
set -euo pipefail

mode=${1:-trigger}
case "$mode" in
  trigger|loopback) ;;
  *) echo "usage: $0 [trigger|loopback]" >&2; exit 2 ;;
esac

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
bitstream="$script_dir/kr260_${mode}.bin"
overlay="$script_dir/kr260-${mode}.dtbo"
test -f "$bitstream"
test -f "$overlay"

sudo cp "$bitstream" /lib/firmware/
sudo cp "$overlay" /lib/firmware/
if command -v xmutil >/dev/null 2>&1; then
  sudo xmutil unloadapp >/dev/null 2>&1 || true
fi
sudo modprobe uio_pdrv_genirq of_id=generic-uio
sudo fpgautil -b "/lib/firmware/$(basename "$bitstream")" \
  -o "/lib/firmware/$(basename "$overlay")"
sudo modprobe u-dma-buf

echo "Loaded $mode overlay"
ls -l /dev/uio* /dev/udmabuf0 /dev/udmabuf1
