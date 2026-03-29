"""
VMware .vmx configuration file parser.
Extracts VM settings: CPU, memory, disks, networks, etc.
"""
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DiskInfo:
    filename: str
    adapter_type: str  # scsi, ide, sata, nvme
    controller_id: int
    unit_id: int
    size_kb: int = 0
    mode: str = "persistent"
    thin: bool = False


@dataclass
class NetworkInfo:
    adapter_type: str  # e1000, vmxnet3, etc.
    network_name: str
    mac_address: str = ""
    connected: bool = True


@dataclass
class VMConfig:
    name: str
    display_name: str
    guest_os: str
    num_cpus: int
    cores_per_socket: int
    memory_mb: int
    disks: List[DiskInfo] = field(default_factory=list)
    networks: List[NetworkInfo] = field(default_factory=list)
    firmware: str = "bios"  # bios or efi
    source_file: str = ""
    hardware_version: int = 0
    annotations: str = ""
    extra: Dict[str, str] = field(default_factory=dict)


class VmxParser:
    """Parse VMware .vmx files into VMConfig."""

    # Disk controller prefixes
    DISK_PREFIXES = ["scsi", "ide", "sata", "nvme"]

    # Network adapter pattern
    NET_PATTERN = re.compile(r"^ethernet(\d+)\.")

    def parse(self, vmx_path: str) -> VMConfig:
        raw = self._read_vmx(vmx_path)
        return self._build_config(raw, vmx_path)

    def _read_vmx(self, path: str) -> Dict[str, str]:
        result = {}
        encodings = ["utf-8", "utf-8-sig", "shift_jis", "cp932", "latin-1"]
        content = None
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        if content is None:
            with open(path, "r", encoding="latin-1") as f:
                content = f.read()

        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().lower()
            value = value.strip().strip('"')
            result[key] = value
        return result

    def _build_config(self, raw: Dict[str, str], vmx_path: str) -> VMConfig:
        name = raw.get("displayname", os.path.splitext(os.path.basename(vmx_path))[0])

        config = VMConfig(
            name=self._sanitize_name(name),
            display_name=name,
            guest_os=raw.get("guestos", "other"),
            num_cpus=int(raw.get("numvcpus", "1")),
            cores_per_socket=int(raw.get("cpuid.corespersocket", "1")),
            memory_mb=int(raw.get("memsize", "1024")),
            firmware=self._detect_firmware(raw),
            source_file=vmx_path,
            hardware_version=self._parse_hw_version(raw),
            annotations=raw.get("annotation", ""),
        )

        config.disks = self._parse_disks(raw, vmx_path)
        config.networks = self._parse_networks(raw)

        # Store extra properties
        known_keys = {
            "displayname", "guestos", "numvcpus", "cpuid.corespersocket",
            "memsize", "annotation", "virtualhw.version", "firmware",
        }
        config.extra = {k: v for k, v in raw.items() if k not in known_keys}

        return config

    def _sanitize_name(self, name: str) -> str:
        return re.sub(r"[^\w\-.]", "_", name)

    def _detect_firmware(self, raw: Dict[str, str]) -> str:
        fw = raw.get("firmware", "bios").lower()
        if "efi" in fw:
            return "efi"
        return "bios"

    def _parse_hw_version(self, raw: Dict[str, str]) -> int:
        ver = raw.get("virtualhw.version", "0")
        try:
            return int(ver)
        except ValueError:
            return 0

    def _parse_disks(self, raw: Dict[str, str], vmx_path: str) -> List[DiskInfo]:
        disks = []
        vmx_dir = os.path.dirname(vmx_path)

        for prefix in self.DISK_PREFIXES:
            for ctrl in range(4):
                for unit in range(16):
                    key_base = f"{prefix}{ctrl}:{unit}"
                    fname_key = f"{key_base}.filename"
                    if fname_key not in raw:
                        continue
                    filename = raw[fname_key]
                    if not filename.lower().endswith(".vmdk"):
                        continue

                    # Resolve relative path
                    if not os.path.isabs(filename):
                        filename = os.path.join(vmx_dir, filename)

                    mode = raw.get(f"{key_base}.mode", "persistent")

                    disks.append(DiskInfo(
                        filename=filename,
                        adapter_type=prefix,
                        controller_id=ctrl,
                        unit_id=unit,
                        mode=mode,
                        thin="thin" in raw.get(f"{key_base}.writethru", ""),
                    ))

        return disks

    def _parse_networks(self, raw: Dict[str, str]) -> List[NetworkInfo]:
        nets: Dict[int, NetworkInfo] = {}

        for key, value in raw.items():
            m = self.NET_PATTERN.match(key)
            if not m:
                continue
            idx = int(m.group(1))
            if idx not in nets:
                nets[idx] = NetworkInfo(
                    adapter_type="e1000",
                    network_name="default",
                )

            sub_key = key.split(".", 1)[1] if "." in key else ""
            net = nets[idx]

            if sub_key == "virtualdev":
                net.adapter_type = value
            elif sub_key == "networkname":
                net.network_name = value
            elif sub_key == "generatedaddress":
                net.mac_address = value
            elif sub_key == "address":
                if not net.mac_address:
                    net.mac_address = value
            elif sub_key == "startconnected":
                net.connected = value.lower() == "true"
            elif sub_key == "connectiontype":
                if value.lower() == "nat":
                    net.network_name = "default (NAT)"
                elif value.lower() == "bridged":
                    net.network_name = "bridge"

        return [nets[k] for k in sorted(nets.keys())]


# OS mapping: VMware guestOS → libvirt os type hints
GUEST_OS_MAP = {
    "windows9-64": ("windows", "win10"),
    "windows9srv-64": ("windows", "win2k19"),
    "windows2019srv-64": ("windows", "win2k19"),
    "windows2019srvnext-64": ("windows", "win2k22"),
    "windows2022srvnext-64": ("windows", "win2k22"),
    "windows11-64": ("windows", "win11"),
    "windows12-64": ("windows", "win11"),
    "centos-64": ("linux", "centos7.0"),
    "centos7-64": ("linux", "centos7.0"),
    "centos8-64": ("linux", "centos8"),
    "centos9-64": ("linux", "centos-stream9"),
    "rhel7-64": ("linux", "rhel7.0"),
    "rhel8-64": ("linux", "rhel8.0"),
    "rhel9-64": ("linux", "rhel9.0"),
    "ubuntu-64": ("linux", "ubuntu20.04"),
    "ubuntu64guest": ("linux", "ubuntu20.04"),
    "debian10-64": ("linux", "debian10"),
    "debian11-64": ("linux", "debian11"),
    "debian12-64": ("linux", "debian12"),
    "sles15-64": ("linux", "sles15"),
    "other-64": ("linux", "generic"),
    "otherguest": ("linux", "generic"),
    "other": ("linux", "generic"),
    "otherlinux-64": ("linux", "generic"),
    "otherlinux": ("linux", "generic"),
}
