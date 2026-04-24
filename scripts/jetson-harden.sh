#!/usr/bin/env bash
# jetson-harden.sh — Idempotent field-hardening for Jetson AGX Orin
# Run as: sudo bash jetson-harden.sh
# Safe to re-run after re-flash or partial failure.
set -euo pipefail

# Track what was applied vs already configured for summary
declare -A STATUS

# ---------------------------------------------------------------------------
# 1. Headless mode (disable GUI desktop)
# ---------------------------------------------------------------------------
harden_headless() {
    local current_default
    current_default="$(systemctl get-default)"
    if [[ "$current_default" == "multi-user.target" ]]; then
        STATUS[headless]="already"
    else
        systemctl set-default multi-user.target
        STATUS[headless]="applied"
    fi

    if systemctl is-enabled gdm3 &>/dev/null; then
        systemctl disable gdm3
        STATUS[gdm3]="applied"
    else
        STATUS[gdm3]="already"
    fi
}

# ---------------------------------------------------------------------------
# 2. Disable unnecessary services
# ---------------------------------------------------------------------------
harden_services() {
    local svcs=(cups cups-browsed bluetooth ModemManager whoopsie unattended-upgrades)
    local any_changed=false
    for svc in "${svcs[@]}"; do
        if systemctl is-enabled "$svc" &>/dev/null; then
            systemctl disable --now "$svc" 2>/dev/null || true
            any_changed=true
        fi
    done
    if $any_changed; then
        STATUS[services]="applied"
    else
        STATUS[services]="already"
    fi
}

# ---------------------------------------------------------------------------
# 3. Filesystem tuning — noatime,commit=60 on root ext4 mount
# ---------------------------------------------------------------------------
harden_fstab() {
    local fstab="/etc/fstab"

    # Check if the root (/) ext4 mount already has noatime
    if grep -E '^\S+\s+/\s+ext4\s' "$fstab" | grep -q 'noatime'; then
        STATUS[fstab]="already"
        return
    fi

    # Backup before modifying
    cp "$fstab" "${fstab}.bak"
    echo "  fstab backup saved to ${fstab}.bak"

    # Conservative sed: match only the root (/) ext4 mount line.
    # Appends noatime,commit=60 to the existing options field.
    sed -i -E '/^\S+\s+\/\s+ext4\s/ s|(ext4\s+)(\S+)|\1\2,noatime,commit=60|' "$fstab"

    echo "  fstab diff:"
    diff "${fstab}.bak" "$fstab" || true
    STATUS[fstab]="applied"
}

# ---------------------------------------------------------------------------
# 4. Log rotation
# ---------------------------------------------------------------------------
harden_logrotate() {
    # --- 4a. logrotate config for mower-jetson logs ---
    local lr_conf="/etc/logrotate.d/mower-jetson"
    local lr_content
    lr_content=$(cat <<'LOGROTATE'
/var/log/mower-jetson/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    maxsize 50M
    create 0640 root adm
}
LOGROTATE
)

    if [[ -f "$lr_conf" ]] && echo "$lr_content" | diff -q - "$lr_conf" &>/dev/null; then
        STATUS[logrotate]="already"
    else
        echo "$lr_content" > "$lr_conf"
        STATUS[logrotate]="applied"
    fi

    # --- 4b. journald limits ---
    local jd_dir="/etc/systemd/journald.conf.d"
    local jd_conf="$jd_dir/mower.conf"
    local jd_content
    jd_content=$(cat <<'JOURNALD'
[Journal]
SystemMaxUse=500M
MaxRetentionSec=7day
JOURNALD
)

    mkdir -p "$jd_dir"
    if [[ -f "$jd_conf" ]] && echo "$jd_content" | diff -q - "$jd_conf" &>/dev/null; then
        STATUS[journald]="already"
    else
        echo "$jd_content" > "$jd_conf"
        STATUS[journald]="applied"
    fi
}

# ---------------------------------------------------------------------------
# 5. OpenBLAS ARM fix
# ---------------------------------------------------------------------------
harden_openblas() {
    if grep -q 'OPENBLAS_CORETYPE=ARMV8' /etc/environment; then
        STATUS[openblas]="already"
    else
        echo 'OPENBLAS_CORETYPE=ARMV8' >> /etc/environment
        STATUS[openblas]="applied"
    fi
}

# ---------------------------------------------------------------------------
# 6. nvpmodel — set to mode 3 (50W) for OAK-D camera + SLAM workloads
# ---------------------------------------------------------------------------
harden_nvpmodel() {
    # Kill nvpmodel_indicator GUI daemon if running — it holds a lock that
    # blocks nvpmodel -m changes indefinitely (common on fresh flash before
    # headless mode takes effect on next boot).
    if pkill -f nvpmodel_indicator 2>/dev/null; then
        sleep 2  # let the lock file release
    fi

    # nvpmodel -q output varies; check the mode ID line
    if nvpmodel -q 2>/dev/null | grep -q 'POWER_MODEL ID=3'; then
        STATUS[nvpmodel]="already"
    else
        # On JetPack 6.2.2 (L4T 36.5), switching power modes may require a
        # reboot. Without --force nvpmodel hangs waiting for interactive
        # confirmation. --force auto-reboots if needed; the hardening script
        # is idempotent so re-run after reboot will skip completed steps.
        nvpmodel --force -m 3
        STATUS[nvpmodel]="applied"
    fi
}

# ---------------------------------------------------------------------------
# 7. Hardware watchdog — drop-in config (survives apt upgrades)
# ---------------------------------------------------------------------------
harden_watchdog() {
    local wd_dir="/etc/systemd/system.conf.d"
    local wd_conf="$wd_dir/watchdog.conf"
    local wd_content
    wd_content=$(cat <<'WATCHDOG'
[Manager]
RuntimeWatchdogSec=30
WATCHDOG
)

    mkdir -p "$wd_dir"
    if [[ -f "$wd_conf" ]] && echo "$wd_content" | diff -q - "$wd_conf" &>/dev/null; then
        STATUS[watchdog]="already"
    else
        echo "$wd_content" > "$wd_conf"
        STATUS[watchdog]="applied"
    fi
}

# ---------------------------------------------------------------------------
# 8. apt-mark hold L4T packages
# ---------------------------------------------------------------------------
harden_apt_hold() {
    local pkgs=(
        nvidia-l4t-kernel
        nvidia-l4t-kernel-dtbs
        nvidia-l4t-kernel-headers
        nvidia-l4t-bootloader
        nvidia-l4t-initrd
        nvidia-l4t-xusb-firmware
    )
    local any_changed=false
    local held
    held="$(apt-mark showhold)"
    for pkg in "${pkgs[@]}"; do
        if ! echo "$held" | grep -q "^${pkg}$"; then
            apt-mark hold "$pkg"
            any_changed=true
        fi
    done
    if $any_changed; then
        STATUS[apt_hold]="applied"
    else
        STATUS[apt_hold]="already"
    fi
}

# ---------------------------------------------------------------------------
# 9. SSH hardening — drop-in config for sshd
# ---------------------------------------------------------------------------
harden_ssh() {
    local conf="/etc/ssh/sshd_config.d/90-mower-hardening.conf"
    # Allow the invoking user (via SUDO_USER) and root
    local ssh_user="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"
    local desired
    desired=$(cat <<SSHEOF
# Mower rover SSH hardening — managed by jetson-harden.sh
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
AllowUsers ${ssh_user}
X11Forwarding no
AllowTcpForwarding no
ClientAliveInterval 60
ClientAliveCountMax 5
AcceptEnv MOWER_CORRELATION_ID
SSHEOF
)

    if [[ -f "$conf" ]] && diff -q <(echo "$desired") "$conf" &>/dev/null; then
        STATUS[ssh_hardening]="already"
        return
    fi

    echo "$desired" > "$conf"
    chmod 644 "$conf"
    systemctl restart sshd
    STATUS[ssh_hardening]="applied"
}

# ---------------------------------------------------------------------------
# 10. OAK-D udev rules — permissions, autosuspend disable, symlink
# ---------------------------------------------------------------------------
harden_oakd_udev() {
    local rules_file="/etc/udev/rules.d/80-oakd-usb.rules"
    local rules_content
    rules_content=$(cat <<'UDEV'
# /etc/udev/rules.d/80-oakd-usb.rules
# 1. Grant non-root access to OAK-D (Movidius VPU vendor ID 03e7)
SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"

# 2. Disable USB autosuspend for the device
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/autosuspend}="-1"
SUBSYSTEM=="usb", ATTR{idVendor}=="03e7", ATTR{power/control}="on"

# 3. Create a stable symlink for the OAK-D
SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", SYMLINK+="oakd"
UDEV
)

    if [[ -f "$rules_file" ]] && echo "$rules_content" | diff -q - "$rules_file" &>/dev/null; then
        STATUS[oakd_udev]="already"
    else
        echo "$rules_content" > "$rules_file"
        udevadm control --reload-rules && udevadm trigger
        STATUS[oakd_udev]="applied"
    fi
}

# ---------------------------------------------------------------------------
# 11. USB kernel params — autosuspend disable, usbfs buffer increase
# ---------------------------------------------------------------------------
harden_usb_params() {
    local extlinux="/boot/extlinux/extlinux.conf"

    if [[ ! -f "$extlinux" ]]; then
        STATUS[usb_params]="skip:no_extlinux"
        return
    fi

    local need_autosuspend=false
    local need_usbfs=false

    if ! grep -q 'usbcore\.autosuspend=-1' "$extlinux"; then
        need_autosuspend=true
    fi
    if ! grep -q 'usbcore\.usbfs_memory_mb=1000' "$extlinux"; then
        need_usbfs=true
    fi

    if ! $need_autosuspend && ! $need_usbfs; then
        STATUS[usb_params]="already"
        return
    fi

    cp "$extlinux" "${extlinux}.bak"
    echo "  extlinux backup saved to ${extlinux}.bak"

    if $need_autosuspend; then
        sed -i '/^\s*APPEND / s/$/ usbcore.autosuspend=-1/' "$extlinux"
    fi
    if $need_usbfs; then
        sed -i '/^\s*APPEND / s/$/ usbcore.usbfs_memory_mb=1000/' "$extlinux"
    fi

    echo "  extlinux diff:"
    diff "${extlinux}.bak" "$extlinux" || true
    STATUS[usb_params]="applied"
}

# ---------------------------------------------------------------------------
# 12. jetson_clocks — lock clocks at boot via systemd service
# ---------------------------------------------------------------------------
harden_jetson_clocks() {
    local svc_file="/etc/systemd/system/jetson-clocks.service"
    local svc_content
    svc_content=$(cat <<'JCLOCKS'
[Unit]
Description=Lock Jetson clocks to nvpmodel maximums
After=nvpmodel.service

[Service]
Type=oneshot
ExecStart=/usr/bin/jetson_clocks
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
JCLOCKS
)

    if [[ -f "$svc_file" ]] && echo "$svc_content" | diff -q - "$svc_file" &>/dev/null; then
        STATUS[jetson_clocks]="already"
    else
        echo "$svc_content" > "$svc_file"
        systemctl daemon-reload
        systemctl enable jetson-clocks.service
        STATUS[jetson_clocks]="applied"
    fi
}

# ---------------------------------------------------------------------------
# 13. RTAB-Map — build from source with CUDA/OpenCV
# ---------------------------------------------------------------------------
harden_rtabmap() {
    local tag="v0.23.1"
    local src_dir="/opt/rtabmap-src"

    # Already installed?
    if command -v rtabmap &>/dev/null && rtabmap --version 2>&1 | grep -q '0\.23'; then
        STATUS[rtabmap]="already"
        return
    fi

    # Build dependencies
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        cmake build-essential git \
        libopencv-dev libsqlite3-dev libpcl-dev \
        libboost-all-dev libeigen3-dev libsuitesparse-dev

    # Clone (or re-use existing checkout)
    if [[ -d "$src_dir/.git" ]]; then
        echo "  Re-using existing RTAB-Map source at $src_dir"
        cd "$src_dir" && git checkout "$tag" 2>/dev/null || true
    else
        rm -rf "$src_dir"
        git clone --depth 1 --branch "$tag" \
            https://github.com/introlab/rtabmap.git "$src_dir"
    fi

    mkdir -p "${src_dir}/build" && cd "${src_dir}/build"
    cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DWITH_CUDA=ON \
        -DWITH_QT=OFF \
        -DWITH_PYTHON=OFF \
        -DBUILD_EXAMPLES=OFF

    make -j"$(nproc)"
    make install
    ldconfig

    # Verify
    if ! rtabmap --version 2>&1 | grep -q '0\.23'; then
        echo "ERROR: RTAB-Map install verification failed" >&2
        STATUS[rtabmap]="failed"
        return 1
    fi
    STATUS[rtabmap]="applied"
}

# ---------------------------------------------------------------------------
# 14. depthai-core C++ SDK — build from source
# ---------------------------------------------------------------------------
harden_depthai_core() {
    local src_dir="/opt/depthai-core-src"
    local marker="/usr/local/lib/libdepthai-core.so"

    if [[ -f "$marker" ]]; then
        STATUS[depthai_core]="already"
        return
    fi

    apt-get install -y --no-install-recommends \
        cmake build-essential git libusb-1.0-0-dev

    if [[ -d "$src_dir/.git" ]]; then
        echo "  Re-using existing depthai-core source at $src_dir"
    else
        rm -rf "$src_dir"
        git clone --depth 1 --recursive \
            https://github.com/luxonis/depthai-core.git "$src_dir"
    fi

    mkdir -p "${src_dir}/build" && cd "${src_dir}/build"
    cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DBUILD_SHARED_LIBS=ON

    make -j"$(nproc)"
    make install
    ldconfig

    if [[ ! -f "$marker" ]]; then
        echo "ERROR: depthai-core install verification failed" >&2
        STATUS[depthai_core]="failed"
        return 1
    fi
    STATUS[depthai_core]="applied"
}

# ---------------------------------------------------------------------------
# 15. RTAB-Map SLAM node — build custom C++ binary
# ---------------------------------------------------------------------------
harden_slam_node() {
    local build_script
    build_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../contrib/rtabmap_slam_node/build.sh"
    local binary="/usr/local/bin/rtabmap_slam_node"

    if [[ -f "$binary" ]]; then
        STATUS[slam_node]="already"
        return
    fi

    if [[ ! -f "$build_script" ]]; then
        echo "  WARN: $build_script not found — skipping SLAM node build"
        STATUS[slam_node]="skip:no_build_script"
        return
    fi

    bash "$build_script"
    if [[ ! -f "$binary" ]]; then
        echo "ERROR: SLAM node build did not produce $binary" >&2
        STATUS[slam_node]="failed"
        return 1
    fi
    STATUS[slam_node]="applied"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print_summary() {
    echo ""
    echo "=========================================="
    echo " jetson-harden.sh — Summary"
    echo "=========================================="
    local labels=(
        "headless:Headless mode (multi-user.target)"
        "gdm3:Disable gdm3"
        "services:Disable unnecessary services"
        "fstab:Filesystem tuning (noatime,commit=60)"
        "logrotate:Logrotate config"
        "journald:Journald limits"
        "openblas:OPENBLAS_CORETYPE=ARMV8"
        "nvpmodel:nvpmodel mode 3 (50W)"
        "watchdog:Hardware watchdog (30s)"
        "apt_hold:apt-mark hold L4T packages"
        "ssh_hardening:SSH hardening (sshd drop-in)"
        "oakd_udev:OAK-D udev rules (80-oakd-usb.rules)"
        "usb_params:USB kernel params (autosuspend, usbfs_memory_mb)"
        "jetson_clocks:jetson_clocks service (lock clocks at boot)"
        "rtabmap:RTAB-Map 0.23.x (source build, CUDA+OpenCV)"
        "depthai_core:depthai-core C++ SDK (source build)"
        "slam_node:RTAB-Map SLAM node binary (custom C++)"
    )
    for entry in "${labels[@]}"; do
        local key="${entry%%:*}"
        local label="${entry#*:}"
        local st="${STATUS[$key]:-unknown}"
        if [[ "$st" == "applied" ]]; then
            printf "  ✓  %s\n" "$label"
        elif [[ "$st" == "already" ]]; then
            printf "  ●  %s (already configured)\n" "$label"
        elif [[ "$st" == skip:* ]]; then
            printf "  ⊘  %s (skipped: %s)\n" "$label" "${st#skip:}"
        else
            printf "  ?  %s (unknown)\n" "$label"
        fi
    done
    echo "=========================================="
    echo "Done. Reboot to apply all changes."
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    echo "jetson-harden.sh — Idempotent field-hardening for Jetson AGX Orin (15 steps)"
    echo ""

    if [[ "$(id -u)" -ne 0 ]]; then
        echo "ERROR: This script must be run as root (sudo)." >&2
        exit 1
    fi

    echo "[1/15] Headless mode..."
    harden_headless

    echo "[2/15] Disabling unnecessary services..."
    harden_services

    echo "[3/15] Filesystem tuning..."
    harden_fstab

    echo "[4/15] Log rotation & journald limits..."
    harden_logrotate

    echo "[5/15] OpenBLAS ARM fix..."
    harden_openblas

    echo "[6/15] nvpmodel (50W)..."
    harden_nvpmodel

    echo "[7/15] Hardware watchdog..."
    harden_watchdog

    echo "[8/15] apt-mark hold L4T packages..."
    harden_apt_hold

    echo "[9/15] SSH hardening..."
    harden_ssh

    echo "[10/15] OAK-D udev rules..."
    harden_oakd_udev

    echo "[11/15] USB kernel params..."
    harden_usb_params

    echo "[12/15] jetson_clocks service..."
    harden_jetson_clocks

    echo "[13/15] RTAB-Map (source build)..."
    harden_rtabmap

    echo "[14/15] depthai-core C++ SDK (source build)..."
    harden_depthai_core

    echo "[15/15] RTAB-Map SLAM node binary..."
    harden_slam_node

    print_summary
}

main "$@"
