"""
VMware to KVM / Nutanix Migration Tool
A GUI application that converts VMware VMs (.vmx/.ovf/.ova) to KVM (libvirt) or Nutanix AHV.

Architecture:
  - Model: src/gui_model.py (ConversionState, constants)
  - View:  src/gui_view.py  (VMware2KVMView - widget creation/layout)
  - Controller: src/gui_controller.py (ConversionController - event handling/logic)

Usage:
  GUI:  python main.py
  CLI:  python main.py --input ./input --output ./output --target kvm
"""
import os
import sys
import argparse

# Support running as script or frozen exe
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)

from src.converter import Converter, ConversionOptions
from src.i18n import I18n


def run_cli(args):
    """Execute conversion without GUI."""
    print("=" * 60)
    print("VMware to KVM / Nutanix Migration Tool (CLI Mode)")
    print("=" * 60)

    input_dir = args.input.strip()
    output_dir = args.output.strip()

    if not os.path.isdir(input_dir):
        print(f"[ERROR] Input directory does not exist: {input_dir}")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")
    print(f"Target: {args.target}")
    print()

    extensions = [e.strip() for e in args.ext.split(",")]

    # Resolve network map path
    network_map_path = ""
    if hasattr(args, "network_map") and args.network_map:
        network_map_path = args.network_map
    else:
        # Auto-detect network_map.json in base dir
        default_nmap = os.path.join(BASE_DIR, "network_map.json")
        if os.path.isfile(default_nmap):
            network_map_path = default_nmap
            print(f"Network map: {network_map_path}")

    options = ConversionOptions(
        target=args.target,
        convert_disk=not args.no_disk,
        generate_config=True,
        generate_script=True,
        compress_qcow2=not args.no_compress,
        thin_provision=True,
        nutanix_container=args.container,
        extensions=extensions,
        network_map_path=network_map_path,
        windows_bus_fallback=not args.no_win_fallback,
        virtio_win_iso=args.virtio_iso if hasattr(args, "virtio_iso") else "",
    )

    converter = Converter()
    i18n = I18n(args.lang)

    vm_files = converter.scan_vms(input_dir, extensions)
    if not vm_files:
        print("[INFO] No VMware files found.")
        sys.exit(0)

    print(f"Found {len(vm_files)} VM file(s)")
    print()

    def log_fn(msg_tuple):
        key, kwargs = msg_tuple
        print(i18n.t(key, **kwargs))

    def progress_fn(current, total):
        if total > 0 and current < total:
            print(f"[{current+1}/{total}]", end=" ")

    # Pre-flight check: disk space
    if options.convert_disk:
        if not converter.preflight_check(output_dir, vm_files, log_fn=log_fn):
            print()
            print("[ERROR] Pre-flight check failed: insufficient disk space.")
            print("Use --no-disk to skip disk conversion, or free up space.")
            sys.exit(1)

    results = converter.convert_all(input_dir, output_dir, options,
                                    log_fn=log_fn, progress_fn=progress_fn)

    print()
    print("=" * 60)
    success = sum(1 for r in results if r.success)
    print(f"Complete: {success}/{len(results)} succeeded")

    for r in results:
        if r.success and r.config:
            print(f"  OK  {r.config.display_name} (CPU:{r.config.num_cpus} MEM:{r.config.memory_mb}MB)")
            if r.kvm_result:
                print(f"      KVM XML:    {r.kvm_result['xml_path']}")
                print(f"      KVM Script: {r.kvm_result['import_script']}")
            if r.nutanix_result:
                print(f"      Nutanix:    {r.nutanix_result['acli_script']}")
        elif not r.success:
            print(f"  NG  {r.vm_name}: {r.error}")

    # Report location
    report_csv = os.path.join(output_dir, "migration_report.csv")
    report_log = os.path.join(output_dir, "migration.log")
    if os.path.isfile(report_csv):
        print(f"Report: {report_csv}")
    if os.path.isfile(report_log):
        print(f"Log:    {report_log}")
    print("=" * 60)


def run_gui():
    """Launch tkinter GUI."""
    import tkinter as tk
    from src.gui_view import VMware2KVMView
    from src.gui_controller import ConversionController

    root = tk.Tk()
    i18n = I18n("ja")
    view = VMware2KVMView(root, i18n)
    controller = ConversionController(view, i18n)

    # Set default paths
    default_input = os.path.join(BASE_DIR, "input")
    default_output = os.path.join(BASE_DIR, "output")
    if os.path.isdir(default_input):
        view.input_var.set(default_input)
    if not view.output_var.get():
        view.output_var.set(default_output)

    root.mainloop()


def main():
    parser = argparse.ArgumentParser(
        description="VMware to KVM / Nutanix Migration Tool"
    )
    parser.add_argument("--input", "-i", help="Input directory containing VMware files")
    parser.add_argument("--output", "-o", help="Output directory")
    parser.add_argument("--target", "-t", choices=["kvm", "nutanix", "both"],
                        default="kvm", help="Target platform (default: kvm)")
    parser.add_argument("--ext", default=".vmx,.ovf,.ova",
                        help="File extensions to scan (default: .vmx,.ovf,.ova)")
    parser.add_argument("--no-disk", action="store_true",
                        help="Skip disk conversion (generate config only)")
    parser.add_argument("--no-compress", action="store_true",
                        help="Disable qcow2 compression")
    parser.add_argument("--container", default="default-container",
                        help="Nutanix container name")
    parser.add_argument("--lang", default="ja", choices=["ja", "en"],
                        help="Language (default: ja)")
    parser.add_argument("--network-map", default="",
                        help="Path to network_map.json for network mapping")
    parser.add_argument("--no-win-fallback", action="store_true",
                        help="Disable Windows SATA/IDE fallback (use virtio directly)")
    parser.add_argument("--virtio-iso", default="",
                        help="Path to virtio-win.iso")
    parser.add_argument("--gui", action="store_true",
                        help="Force GUI mode")

    args = parser.parse_args()

    if args.input and not args.gui:
        run_cli(args)
    else:
        run_gui()


if __name__ == "__main__":
    main()
