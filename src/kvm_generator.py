"""
KVM (libvirt) configuration generator.
Generates libvirt XML domain definitions and qemu-img conversion commands.
"""
import os
import shlex
from typing import List

from .vmx_parser import VMConfig, DiskInfo, GUEST_OS_MAP


class KvmGenerator:
    """Generate libvirt XML and disk conversion scripts for KVM."""

    # Default path to virtio-win ISO for Windows guest driver installation
    VIRTIO_WIN_ISO = "/usr/share/virtio-win/virtio-win.iso"

    def generate(self, config: VMConfig, output_dir: str,
                 compress: bool = True, thin: bool = True,
                 network_map: dict = None,
                 windows_bus_fallback: bool = True,
                 virtio_win_iso: str = "") -> dict:
        """
        Generate KVM migration artifacts.
        Returns dict with paths to generated files and conversion commands.
        """
        vm_dir = os.path.join(output_dir, config.name)
        os.makedirs(vm_dir, exist_ok=True)

        result = {
            "xml_path": None,
            "disk_commands": [],
            "disk_mappings": [],
            "import_script": None,
        }

        # Generate disk conversion commands and mappings
        for i, disk in enumerate(config.disks):
            qcow2_name = f"{config.name}-disk{i}.qcow2"
            qcow2_path = os.path.join(vm_dir, qcow2_name)
            cmd = self._disk_convert_cmd(disk.filename, qcow2_path, compress)
            result["disk_commands"].append(cmd)
            result["disk_mappings"].append({
                "source_vmdk": disk.filename,
                "target_qcow2": qcow2_path,
                "adapter": disk.adapter_type,
                "controller": disk.controller_id,
                "unit": disk.unit_id,
            })

        # Determine OS family for driver handling
        os_family, _ = GUEST_OS_MAP.get(config.guest_os.lower(), ("linux", "generic"))

        # Generate libvirt XML
        xml_content = self._generate_xml(
            config, result["disk_mappings"],
            network_map=network_map,
            windows_bus_fallback=windows_bus_fallback,
            virtio_win_iso=virtio_win_iso,
        )
        xml_path = os.path.join(vm_dir, f"{config.name}.xml")
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml_content)
        result["xml_path"] = xml_path

        # Generate import shell script
        script_content = self._generate_import_script(config, result, os_family, virtio_win_iso)
        script_path = os.path.join(vm_dir, f"import_{config.name}.sh")
        with open(script_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(script_content)
        result["import_script"] = script_path

        return result

    def _disk_convert_cmd(self, source: str, target: str, compress: bool) -> List[str]:
        cmd = ["qemu-img", "convert", "-f", "vmdk", "-O", "qcow2"]
        if compress:
            cmd.append("-c")
        cmd.extend([source, target])
        return cmd

    def _generate_xml(self, config: VMConfig, disk_mappings: list,
                       network_map: dict = None,
                       windows_bus_fallback: bool = True,
                       virtio_win_iso: str = "") -> str:
        os_family, os_variant = GUEST_OS_MAP.get(
            config.guest_os.lower(), ("linux", "generic")
        )
        is_windows = os_family == "windows"

        memory_kb = config.memory_mb * 1024
        sockets = max(1, config.num_cpus // max(1, config.cores_per_socket))

        lines = []
        lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        lines.append(f'<domain type="kvm">')
        lines.append(f'  <name>{config.name}</name>')
        lines.append(f'  <metadata>')
        lines.append(f'    <!-- Migrated from VMware: {config.display_name} -->')
        lines.append(f'    <!-- Source: {os.path.basename(config.source_file)} -->')
        lines.append(f'    <!-- Guest OS: {config.guest_os} -->')
        if is_windows and windows_bus_fallback:
            lines.append(f'    <!-- NOTE: Disk bus set to SATA for BSOD avoidance. -->')
            lines.append(f'    <!--   After installing virtio drivers, change bus to "virtio" for better performance. -->')
        lines.append(f'  </metadata>')
        lines.append(f'  <memory unit="KiB">{memory_kb}</memory>')
        lines.append(f'  <currentMemory unit="KiB">{memory_kb}</currentMemory>')
        lines.append(f'  <vcpu placement="static">{config.num_cpus}</vcpu>')
        lines.append(f'  <cpu mode="host-passthrough">')
        lines.append(f'    <topology sockets="{sockets}" cores="{config.cores_per_socket}" threads="1"/>')
        lines.append(f'  </cpu>')

        # OS section
        lines.append(f'  <os>')
        if config.firmware == "efi":
            lines.append(f'    <type arch="x86_64" machine="q35">hvm</type>')
            lines.append(f'    <loader readonly="yes" type="pflash">/usr/share/OVMF/OVMF_CODE.fd</loader>')
            lines.append(f'    <nvram>/var/lib/libvirt/qemu/nvram/{config.name}_VARS.fd</nvram>')
        else:
            lines.append(f'    <type arch="x86_64" machine="pc-i440fx-latest">hvm</type>')
        lines.append(f'    <boot dev="hd"/>')
        lines.append(f'  </os>')

        # Features
        lines.append(f'  <features>')
        lines.append(f'    <acpi/>')
        lines.append(f'    <apic/>')
        if is_windows:
            lines.append(f'    <hyperv>')
            lines.append(f'      <relaxed state="on"/>')
            lines.append(f'      <vapic state="on"/>')
            lines.append(f'      <spinlocks state="on" retries="8191"/>')
            lines.append(f'    </hyperv>')
        lines.append(f'  </features>')

        # Clock
        if is_windows:
            lines.append(f'  <clock offset="localtime">')
            lines.append(f'    <timer name="rtc" tickpolicy="catchup"/>')
            lines.append(f'    <timer name="pit" tickpolicy="delay"/>')
            lines.append(f'    <timer name="hpet" present="no"/>')
            lines.append(f'    <timer name="hypervclock" present="yes"/>')
            lines.append(f'  </clock>')
        else:
            lines.append(f'  <clock offset="utc">')
            lines.append(f'    <timer name="rtc" tickpolicy="catchup"/>')
            lines.append(f'    <timer name="pit" tickpolicy="delay"/>')
            lines.append(f'  </clock>')

        # Devices
        lines.append(f'  <devices>')
        lines.append(f'    <emulator>/usr/bin/qemu-system-x86_64</emulator>')

        # Determine disk bus: Windows fallback to SATA/IDE to avoid BSOD
        for i, dm in enumerate(disk_mappings):
            dev_letter = chr(ord("a") + i)
            if is_windows and windows_bus_fallback:
                # Safe fallback: SATA for EFI, IDE for BIOS
                bus = "sata" if config.firmware == "efi" else "ide"
                dev_prefix = "sd" if bus == "sata" else "hd"
            elif config.firmware == "efi":
                bus = "sata"
                dev_prefix = "sd"
            else:
                bus = "virtio"
                dev_prefix = "vd"
            lines.append(f'    <disk type="file" device="disk">')
            lines.append(f'      <driver name="qemu" type="qcow2" cache="writeback" discard="unmap"/>')
            lines.append(f'      <source file="{dm["target_qcow2"]}"/>')
            lines.append(f'      <target dev="{dev_prefix}{dev_letter}" bus="{bus}"/>')
            lines.append(f'    </disk>')

        # CD-ROM: virtio-win.iso for Windows driver installation
        iso_path = virtio_win_iso or (self.VIRTIO_WIN_ISO if is_windows else "")
        if is_windows and iso_path:
            lines.append(f'    <!-- virtio-win.iso: Install VirtIO drivers from this CD after first boot -->')
            lines.append(f'    <disk type="file" device="cdrom">')
            lines.append(f'      <driver name="qemu" type="raw"/>')
            lines.append(f'      <source file="{iso_path}"/>')
            lines.append(f'      <target dev="sda" bus="sata"/>')
            lines.append(f'      <readonly/>')
            lines.append(f'    </disk>')
        else:
            lines.append(f'    <disk type="file" device="cdrom">')
            lines.append(f'      <driver name="qemu" type="raw"/>')
            lines.append(f'      <target dev="sda" bus="sata"/>')
            lines.append(f'      <readonly/>')
            lines.append(f'    </disk>')

        # Network interfaces (with network_map support and MAC preservation)
        for net in config.networks:
            model = self._map_nic_model(net.adapter_type)
            mapped = self._resolve_network(net.network_name, network_map)
            if mapped.get("type") == "bridge":
                lines.append(f'    <interface type="bridge">')
                lines.append(f'      <source bridge="{mapped["name"]}"/>')
            else:
                lines.append(f'    <interface type="network">')
                lines.append(f'      <source network="{mapped["name"]}"/>')
            lines.append(f'      <model type="{model}"/>')
            if net.mac_address:
                lines.append(f'      <mac address="{net.mac_address}"/>')
            lines.append(f'    </interface>')

        # Graphics and input
        lines.append(f'    <graphics type="vnc" port="-1" autoport="yes" listen="0.0.0.0"/>')
        lines.append(f'    <video>')
        lines.append(f'      <model type="qxl" ram="65536" vram="65536"/>')
        lines.append(f'    </video>')
        lines.append(f'    <input type="tablet" bus="usb"/>')

        # Serial console
        lines.append(f'    <serial type="pty">')
        lines.append(f'      <target port="0"/>')
        lines.append(f'    </serial>')
        lines.append(f'    <console type="pty">')
        lines.append(f'      <target type="serial" port="0"/>')
        lines.append(f'    </console>')

        # Channel for guest agent
        lines.append(f'    <channel type="unix">')
        lines.append(f'      <target type="virtio" name="org.qemu.guest_agent.0"/>')
        lines.append(f'    </channel>')

        lines.append(f'  </devices>')
        lines.append(f'</domain>')

        return "\n".join(lines) + "\n"

    def _map_nic_model(self, vmware_type: str) -> str:
        mapping = {
            "vmxnet3": "virtio",
            "vmxnet2": "virtio",
            "vmxnet": "virtio",
            "e1000": "e1000",
            "e1000e": "e1000e",
            "vlance": "rtl8139",
        }
        return mapping.get(vmware_type.lower(), "virtio")

    def _resolve_network(self, vmware_net_name: str, network_map: dict = None) -> dict:
        """Resolve VMware network name to KVM network using network_map."""
        if network_map and "kvm" in network_map:
            kvm_map = network_map["kvm"]
            if vmware_net_name in kvm_map:
                entry = kvm_map[vmware_net_name]
                if isinstance(entry, dict):
                    return {
                        "type": entry.get("type", "network"),
                        "name": entry.get("name", "default"),
                    }
                return {"type": "network", "name": str(entry)}
        return {"type": "network", "name": "default"}

    def _generate_import_script(self, config: VMConfig, result: dict,
                                os_family: str = "linux",
                                virtio_win_iso: str = "") -> str:
        is_windows = os_family == "windows"
        lines = []
        lines.append("#!/bin/bash")
        lines.append(f"# KVM Import Script for: {config.display_name}")
        lines.append(f"# Migrated from VMware")
        lines.append(f"# Generated by VMware2KVM")
        lines.append("")
        lines.append("set -e")
        lines.append("")

        lines.append("echo '=== Step 1: Convert disk images ==='")
        for cmd in result["disk_commands"]:
            target_path = cmd[-1]
            lines.append(f"echo 'Converting: {os.path.basename(target_path)}'")
            lines.append(shlex.join(cmd))
        lines.append("")

        lines.append("echo '=== Step 2: Define VM in libvirt ==='")
        lines.append(f'virsh define "{result["xml_path"]}"')
        lines.append("")

        lines.append("echo '=== Step 3: Start VM ==='")
        lines.append(f"# Uncomment the next line to auto-start the VM")
        lines.append(f"# virsh start {config.name}")
        lines.append("")

        lines.append("echo '=== Step 4: Optional - Enable autostart ==='")
        lines.append(f"# virsh autostart {config.name}")
        lines.append("")

        # Windows-specific post-migration steps
        if is_windows:
            lines.append("echo '=== Windows Post-Migration Notes ==='")
            lines.append("echo '1. Boot the VM with SATA/IDE bus (current config)'")
            lines.append("echo '2. Install VirtIO drivers from the attached virtio-win.iso CD-ROM'")
            lines.append("echo '   - Storage: viostor / vioscsi'")
            lines.append("echo '   - Network: NetKVM'")
            lines.append("echo '   - Balloon: Balloon'")
            lines.append("echo '   - Serial: vioserial'")
            lines.append("echo '3. After driver installation, edit the XML to change disk bus to virtio'")
            lines.append(f"echo '   Command: virsh edit {config.name}'")
            lines.append("echo '4. Reboot the VM'")
            iso = virtio_win_iso or self.VIRTIO_WIN_ISO
            lines.append(f"echo 'virtio-win ISO: {iso}'")
            lines.append("")

        lines.append(f"echo 'Import complete for: {config.display_name}'")
        lines.append(f"echo 'Use: virsh start {config.name} to boot the VM'")

        return "\n".join(lines) + "\n"
