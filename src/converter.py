"""
Main conversion orchestrator.
Scans input folder, parses VMware files, and dispatches to generators.
"""
import csv
import json
import logging
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .vmx_parser import VmxParser, VMConfig
from .ovf_parser import OvfParser
from .kvm_generator import KvmGenerator
from .nutanix_generator import NutanixGenerator


@dataclass
class ConversionOptions:
    target: str = "kvm"  # "kvm", "nutanix", "both"
    convert_disk: bool = True
    generate_config: bool = True
    generate_script: bool = True
    compress_qcow2: bool = True
    thin_provision: bool = True
    nutanix_container: str = "default-container"
    extensions: List[str] = field(default_factory=lambda: [".vmx", ".ovf", ".ova"])
    network_map_path: str = ""
    windows_bus_fallback: bool = True
    virtio_win_iso: str = ""


@dataclass
class ConversionResult:
    vm_name: str
    success: bool
    config: Optional[VMConfig] = None
    kvm_result: Optional[dict] = None
    nutanix_result: Optional[dict] = None
    error: str = ""
    disk_converted: bool = False
    elapsed_sec: float = 0.0


class Converter:
    """Orchestrate VMware → KVM/Nutanix conversion."""

    def __init__(self):
        self.vmx_parser = VmxParser()
        self.ovf_parser = OvfParser()
        self.kvm_gen = KvmGenerator()
        self.nutanix_gen = NutanixGenerator()
        self._stop_requested = False
        self._network_map: Optional[Dict] = None

    def stop(self):
        self._stop_requested = True

    def load_network_map(self, path: str) -> Dict:
        """Load network mapping from a JSON file."""
        if not path or not os.path.isfile(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def scan_vms(self, input_dir: str, extensions: List[str]) -> List[str]:
        """Scan input directory for VMware VM files."""
        found = []
        ext_set = {e.lower() for e in extensions}

        for root, dirs, files in os.walk(input_dir):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in ext_set:
                    found.append(os.path.join(root, fname))

        return sorted(found)

    def estimate_total_vmdk_size(self, vm_files: List[str]) -> int:
        """Estimate total VMDK disk size in bytes from VM definition files."""
        total = 0
        for vm_file in vm_files:
            ext = os.path.splitext(vm_file)[1].lower()
            try:
                if ext == ".vmx":
                    config = self.vmx_parser.parse(vm_file)
                elif ext in (".ovf", ".ova"):
                    config, _ = self.ovf_parser.parse(vm_file)
                else:
                    continue
                for disk in config.disks:
                    if os.path.isfile(disk.filename):
                        total += os.path.getsize(disk.filename)
            except Exception:
                pass
        return total

    def preflight_check(self, output_dir: str, vm_files: List[str],
                        log_fn: Optional[Callable] = None) -> bool:
        """Pre-flight check: verify output disk has enough free space."""
        if log_fn is None:
            log_fn = lambda msg: None

        os.makedirs(output_dir, exist_ok=True)
        vmdk_total = self.estimate_total_vmdk_size(vm_files)

        try:
            disk_usage = shutil.disk_usage(output_dir)
            free_bytes = disk_usage.free
        except OSError:
            log_fn(("log.error", {"message": f"Cannot check disk space for: {output_dir}"}))
            return True  # proceed anyway if can't check

        vmdk_gb = vmdk_total / (1024 ** 3)
        free_gb = free_bytes / (1024 ** 3)

        log_fn(("log.preflight_disk", {
            "vmdk_size": f"{vmdk_gb:.1f}",
            "free_size": f"{free_gb:.1f}",
        }))

        if vmdk_total > 0 and free_bytes < vmdk_total:
            log_fn(("log.preflight_fail", {
                "vmdk_size": f"{vmdk_gb:.1f}",
                "free_size": f"{free_gb:.1f}",
            }))
            return False

        return True

    def convert_all(self, input_dir: str, output_dir: str,
                    options: ConversionOptions,
                    log_fn: Optional[Callable] = None,
                    progress_fn: Optional[Callable] = None) -> List[ConversionResult]:
        """Convert all VMs found in input directory."""
        self._stop_requested = False

        if log_fn is None:
            log_fn = lambda msg: None
        if progress_fn is None:
            progress_fn = lambda current, total: None

        # Load network map if provided
        self._network_map = self.load_network_map(options.network_map_path)

        vm_files = self.scan_vms(input_dir, options.extensions)
        results = []
        total = len(vm_files)

        for i, vm_file in enumerate(vm_files):
            if self._stop_requested:
                break

            progress_fn(i, total)
            t_start = time.time()
            result = self._convert_single(vm_file, output_dir, options, log_fn)
            result.elapsed_sec = time.time() - t_start
            results.append(result)

        progress_fn(total, total)

        # Write migration report and log
        self._write_report(output_dir, results)

        return results

    def _convert_single(self, vm_file: str, output_dir: str,
                        options: ConversionOptions,
                        log_fn: Callable) -> ConversionResult:
        """Convert a single VM."""
        fname = os.path.basename(vm_file)
        ext = os.path.splitext(vm_file)[1].lower()

        try:
            # Parse VM configuration
            config = None
            temp_dir = None

            if ext == ".vmx":
                log_fn(("log.parsing_vmx", {"file": fname}))
                config = self.vmx_parser.parse(vm_file)
            elif ext in (".ovf", ".ova"):
                log_fn(("log.parsing_ovf", {"file": fname}))
                config, temp_dir = self.ovf_parser.parse(vm_file)

            if config is None:
                return ConversionResult(
                    vm_name=fname, success=False,
                    error=f"Unsupported file format: {ext}"
                )

            log_fn(("log.vm_start", {"name": config.display_name}))

            result = ConversionResult(
                vm_name=config.display_name,
                success=True,
                config=config,
            )

            # Generate KVM config
            if options.target in ("kvm", "both") and options.generate_config:
                log_fn(("log.generating_xml", {"name": config.name}))
                kvm_result = self.kvm_gen.generate(
                    config, output_dir,
                    compress=options.compress_qcow2,
                    thin=options.thin_provision,
                    network_map=self._network_map,
                    windows_bus_fallback=options.windows_bus_fallback,
                    virtio_win_iso=options.virtio_win_iso,
                )
                result.kvm_result = kvm_result

                # Attempt disk conversion if requested
                if options.convert_disk:
                    result.disk_converted = self._run_disk_conversion(
                        kvm_result["disk_commands"], log_fn
                    )

            # Generate Nutanix config
            if options.target in ("nutanix", "both") and options.generate_config:
                log_fn(("log.generating_nutanix", {"name": config.name}))
                nutanix_result = self.nutanix_gen.generate(
                    config, output_dir,
                    compress=options.compress_qcow2,
                    container_name=options.nutanix_container,
                    network_map=self._network_map,
                )
                result.nutanix_result = nutanix_result

                # Disk conversion for Nutanix (if KVM didn't already do it)
                if options.convert_disk and not result.disk_converted:
                    result.disk_converted = self._run_disk_conversion(
                        nutanix_result["disk_commands"], log_fn
                    )

            log_fn(("log.vm_done", {"name": config.display_name}))
            return result

        except Exception as e:
            return ConversionResult(
                vm_name=fname, success=False, error=str(e)
            )

    def _run_disk_conversion(self, commands: List[List[str]], log_fn: Callable) -> bool:
        """Try to run qemu-img disk conversions. Returns True if successful."""
        if not commands:
            return True

        qemu_img = shutil.which("qemu-img")
        if not qemu_img:
            log_fn(("error.qemu_not_found", {}))
            for cmd in commands:
                log_fn(("log.cmd_hint", {"cmd": shlex.join(cmd)}))
            log_fn(("log.skip_disk", {}))
            return False

        for cmd in commands:
            if self._stop_requested:
                return False
            # cmd is argv list; replace argv[0] with the resolved qemu-img path
            argv = [qemu_img] + list(cmd[1:])
            target_path = argv[-1]
            cmd_display = shlex.join(argv)
            log_fn(("log.converting_disk", {"file": target_path}))
            log_fn(("log.cmd_hint", {"cmd": cmd_display}))
            try:
                subprocess.run(argv, shell=False, check=True, capture_output=True, text=True)
                log_fn(("log.disk_done", {"file": target_path}))
            except subprocess.CalledProcessError as e:
                log_fn(("log.error", {"message": f"qemu-img failed: {e.stderr}"}))
                log_fn(("log.cmd_hint", {"cmd": cmd_display}))
                return False

        return True

    def _write_report(self, output_dir: str, results: List[ConversionResult]):
        """Write migration_report.csv and migration.log to output directory."""
        if not results:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # --- CSV Report ---
        csv_path = os.path.join(output_dir, "migration_report.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "VM Name", "Status", "CPU", "Memory (MB)", "Disks",
                "Networks", "Firmware", "Guest OS", "Disk Converted",
                "Elapsed (sec)", "Error", "Source File",
            ])
            for r in results:
                cfg = r.config
                writer.writerow([
                    r.vm_name,
                    "OK" if r.success else "NG",
                    cfg.num_cpus if cfg else "",
                    cfg.memory_mb if cfg else "",
                    len(cfg.disks) if cfg else "",
                    len(cfg.networks) if cfg else "",
                    cfg.firmware if cfg else "",
                    cfg.guest_os if cfg else "",
                    "Yes" if r.disk_converted else "No",
                    f"{r.elapsed_sec:.2f}",
                    r.error,
                    cfg.source_file if cfg else "",
                ])

        # --- Log File ---
        log_path = os.path.join(output_dir, "migration.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"VMware2KVM Migration Log\n")
            f.write(f"Generated: {timestamp}\n")
            f.write(f"{'=' * 60}\n\n")

            success = sum(1 for r in results if r.success)
            f.write(f"Total: {len(results)} VMs | Success: {success} | Failed: {len(results) - success}\n\n")

            for r in results:
                status = "OK" if r.success else "NG"
                f.write(f"[{status}] {r.vm_name} ({r.elapsed_sec:.2f}s)\n")
                if r.config:
                    cfg = r.config
                    f.write(f"  CPU: {cfg.num_cpus} vCPU | Memory: {cfg.memory_mb} MB | "
                            f"Disks: {len(cfg.disks)} | Networks: {len(cfg.networks)} | "
                            f"Firmware: {cfg.firmware} | OS: {cfg.guest_os}\n")
                    f.write(f"  Source: {cfg.source_file}\n")
                    # MAC addresses
                    for i, net in enumerate(cfg.networks):
                        mac_info = net.mac_address or "(auto)"
                        f.write(f"  NIC{i}: {net.network_name} [{net.adapter_type}] MAC={mac_info}\n")
                if r.kvm_result:
                    f.write(f"  KVM XML: {r.kvm_result['xml_path']}\n")
                    f.write(f"  KVM Script: {r.kvm_result['import_script']}\n")
                if r.nutanix_result:
                    f.write(f"  Nutanix acli: {r.nutanix_result['acli_script']}\n")
                    f.write(f"  Nutanix API: {r.nutanix_result['api_script']}\n")
                    f.write(f"  Nutanix JSON: {r.nutanix_result['json_spec']}\n")
                if r.error:
                    f.write(f"  ERROR: {r.error}\n")
                f.write(f"\n")
