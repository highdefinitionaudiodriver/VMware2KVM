"""
VMware OVF/OVA file parser.
Parses .ovf XML and extracts VM configuration.
OVA files are tar archives containing .ovf + .vmdk files.
"""
import os
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from .vmx_parser import VMConfig, DiskInfo, NetworkInfo

# OVF namespaces
NS = {
    "ovf": "http://schemas.dmtf.org/ovf/envelope/1",
    "rasd": "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData",
    "vssd": "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData",
    "vmw": "http://www.vmware.com/schema/ovf",
    "vbox": "http://www.virtualbox.org/ovf/machine",
}

# ResourceType codes (CIM standard)
RESOURCE_PROCESSOR = "3"
RESOURCE_MEMORY = "4"
RESOURCE_IDE_CONTROLLER = "5"
RESOURCE_SCSI_CONTROLLER = "6"
RESOURCE_ETHERNET = "10"
RESOURCE_DISK_DRIVE = "17"
RESOURCE_USB_CONTROLLER = "23"
RESOURCE_SATA_CONTROLLER = "20"


class OvfParser:
    """Parse OVF/OVA files into VMConfig."""

    def parse(self, path: str) -> Tuple[VMConfig, str]:
        """
        Parse OVF or OVA file.
        Returns (VMConfig, working_dir) where working_dir contains extracted files.
        """
        if path.lower().endswith(".ova"):
            return self._parse_ova(path)
        else:
            return self._parse_ovf(path), os.path.dirname(path)

    def _parse_ova(self, ova_path: str) -> Tuple[VMConfig, str]:
        extract_dir = tempfile.mkdtemp(prefix="vmware2kvm_")
        with tarfile.open(ova_path, "r:*") as tar:
            tar.extractall(extract_dir, filter="data")

        # Find the .ovf file
        ovf_file = None
        for fname in os.listdir(extract_dir):
            if fname.lower().endswith(".ovf"):
                ovf_file = os.path.join(extract_dir, fname)
                break

        if not ovf_file:
            raise ValueError(f"No .ovf file found in OVA: {ova_path}")

        config = self._parse_ovf(ovf_file)
        config.source_file = ova_path
        return config, extract_dir

    def _parse_ovf(self, ovf_path: str) -> VMConfig:
        tree = ET.parse(ovf_path)
        root = tree.getroot()

        # Extract VM name
        vs = root.find(".//ovf:VirtualSystem", NS)
        name = "unknown"
        if vs is not None:
            name = vs.get("{%s}id" % NS["ovf"], "unknown")

        # Find VirtualHardwareSection
        vhs = root.find(".//ovf:VirtualHardwareSection", NS)
        if vhs is None:
            # Try without namespace
            vhs = root.find(".//{http://schemas.dmtf.org/ovf/envelope/1}VirtualHardwareSection")

        num_cpus = 1
        memory_mb = 1024
        disks: List[DiskInfo] = []
        networks: List[NetworkInfo] = []
        guest_os = "other"
        firmware = "bios"

        # Extract OS section
        os_section = root.find(".//ovf:OperatingSystemSection", NS)
        if os_section is not None:
            os_id = os_section.get("{%s}id" % NS["ovf"], "")
            desc_elem = os_section.find("ovf:Description", NS)
            if desc_elem is not None and desc_elem.text:
                guest_os = desc_elem.text.lower().replace(" ", "")
            vmw_ostype = os_section.get("{%s}osType" % NS["vmw"], "")
            if vmw_ostype:
                guest_os = vmw_ostype

        if vhs is not None:
            # System info
            sys_elem = vhs.find("ovf:System", NS)
            if sys_elem is not None:
                vst = sys_elem.find("vssd:VirtualSystemType", NS)
                if vst is not None and vst.text and "efi" in vst.text.lower():
                    firmware = "efi"

            items = vhs.findall("ovf:Item", NS)
            disk_idx = 0

            for item in items:
                rtype_elem = item.find("rasd:ResourceType", NS)
                if rtype_elem is None:
                    continue
                rtype = rtype_elem.text.strip()

                if rtype == RESOURCE_PROCESSOR:
                    qty = item.find("rasd:VirtualQuantity", NS)
                    if qty is not None and qty.text:
                        num_cpus = int(qty.text)

                elif rtype == RESOURCE_MEMORY:
                    qty = item.find("rasd:VirtualQuantity", NS)
                    units = item.find("rasd:AllocationUnits", NS)
                    if qty is not None and qty.text:
                        mem_val = int(qty.text)
                        if units is not None and units.text:
                            unit_str = units.text.lower()
                            if "giga" in unit_str or "gb" in unit_str:
                                mem_val *= 1024
                            elif "kilo" in unit_str or "kb" in unit_str:
                                mem_val //= 1024
                        memory_mb = mem_val

                elif rtype == RESOURCE_ETHERNET:
                    adapter = "e1000"
                    rsubtype = item.find("rasd:ResourceSubType", NS)
                    if rsubtype is not None and rsubtype.text:
                        adapter = rsubtype.text
                    conn = item.find("rasd:Connection", NS)
                    net_name = conn.text if conn is not None and conn.text else "default"
                    networks.append(NetworkInfo(
                        adapter_type=adapter,
                        network_name=net_name,
                    ))

                elif rtype == RESOURCE_DISK_DRIVE:
                    host_res = item.find("rasd:HostResource", NS)
                    if host_res is not None and host_res.text:
                        # Resolve disk file reference
                        disk_ref = host_res.text
                        disk_file = self._resolve_disk_ref(root, disk_ref, ovf_path)
                        if disk_file:
                            parent = item.find("rasd:Parent", NS)
                            addr = item.find("rasd:AddressOnParent", NS)
                            disks.append(DiskInfo(
                                filename=disk_file,
                                adapter_type="scsi",
                                controller_id=0,
                                unit_id=disk_idx,
                            ))
                            disk_idx += 1

        config = VMConfig(
            name=self._sanitize_name(name),
            display_name=name,
            guest_os=guest_os,
            num_cpus=num_cpus,
            cores_per_socket=1,
            memory_mb=memory_mb,
            disks=disks,
            networks=networks,
            firmware=firmware,
            source_file=ovf_path,
        )
        return config

    def _resolve_disk_ref(self, root, ref: str, ovf_path: str) -> Optional[str]:
        ovf_dir = os.path.dirname(ovf_path)

        # ref is like "ovf:/disk/vmdisk1"
        disk_id = ref.split("/")[-1] if "/" in ref else ref

        # Find in DiskSection
        for disk in root.findall(".//ovf:Disk", NS):
            d_id = disk.get("{%s}diskId" % NS["ovf"], "")
            if d_id == disk_id:
                file_ref = disk.get("{%s}fileRef" % NS["ovf"], "")
                # Resolve file reference
                for fref in root.findall(".//ovf:File", NS):
                    f_id = fref.get("{%s}id" % NS["ovf"], "")
                    if f_id == file_ref:
                        href = fref.get("{%s}href" % NS["ovf"], "")
                        return os.path.join(ovf_dir, href)

        # Fallback: look for vmdk in same dir
        for fname in os.listdir(ovf_dir):
            if fname.lower().endswith(".vmdk"):
                return os.path.join(ovf_dir, fname)

        return None

    def _sanitize_name(self, name: str) -> str:
        import re
        return re.sub(r"[^\w\-.]", "_", name)
