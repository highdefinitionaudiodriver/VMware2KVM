"""
GUI Controller layer.
イベントハンドリング・ビジネスロジック呼び出しを担当。
"""
import os
import shutil
import threading
from tkinter import filedialog, messagebox

from .i18n import I18n
from .gui_view import VMware2KVMView
from .gui_model import ConversionState
from .converter import Converter, ConversionOptions


class ConversionController:
    """Controller: View ↔ Model をつなぐ."""

    def __init__(self, view: VMware2KVMView, i18n: I18n):
        self.view = view
        self.i18n = i18n
        self.converter = Converter()
        self.state = ConversionState()
        self._thread = None
        self._bind_events()

    def _t(self, key: str, **kwargs) -> str:
        return self.i18n.t(key, **kwargs)

    def _bind_events(self):
        self.view.bind_command("input_btn", self._browse_input)
        self.view.bind_command("output_btn", self._browse_output)
        self.view.bind_command("run_btn", self._start_conversion)
        self.view.bind_command("stop_btn", self._stop_conversion)
        self.view.bind_event("lang_combo", "<<ComboboxSelected>>", self._change_language)

    def _browse_input(self):
        path = filedialog.askdirectory(title=self._t("label.input_dir"))
        if path:
            self.view.input_var.set(path)
            # Auto-set output if empty
            if not self.view.output_var.get():
                self.view.output_var.set(os.path.join(os.path.dirname(path), "output"))

    def _browse_output(self):
        path = filedialog.askdirectory(title=self._t("label.output_dir"))
        if path:
            self.view.output_var.set(path)

    def _change_language(self, event=None):
        lang_code = self.view.get_lang_code()
        self.i18n.set_lang(lang_code)
        self.view.refresh_texts()

    def _start_conversion(self):
        input_dir = self.view.input_var.get().strip()
        output_dir = self.view.output_var.get().strip()

        if not input_dir:
            messagebox.showwarning("Warning", self._t("error.no_input"))
            return
        if not output_dir:
            messagebox.showwarning("Warning", self._t("error.no_output"))
            return
        if not os.path.isdir(input_dir):
            messagebox.showerror("Error", self._t("error.input_not_found"))
            return

        os.makedirs(output_dir, exist_ok=True)

        extensions = [e.strip() for e in self.view.extensions_var.get().split(",")]
        target = self.view.get_target_code()

        # Auto-detect network_map.json
        import sys
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_nmap = os.path.join(base, "network_map.json")
        nmap_path = default_nmap if os.path.isfile(default_nmap) else ""

        options = ConversionOptions(
            target=target,
            convert_disk=self.view.convert_disk_var.get(),
            generate_config=self.view.generate_config_var.get(),
            generate_script=self.view.generate_script_var.get(),
            compress_qcow2=self.view.compress_var.get(),
            thin_provision=self.view.thin_var.get(),
            nutanix_container=self.view.container_var.get(),
            extensions=extensions,
            network_map_path=nmap_path,
            windows_bus_fallback=True,
        )

        # Scan first
        vm_files = self.converter.scan_vms(input_dir, extensions)
        if not vm_files:
            messagebox.showinfo("Info", self._t("error.no_vms"))
            return

        # Pre-flight disk space check
        if options.convert_disk:
            def _log_preflight(msg_tuple):
                key, kwargs = msg_tuple
                # just collect for display
                pass

            if not self.converter.preflight_check(output_dir, vm_files, log_fn=_log_preflight):
                vmdk_total = self.converter.estimate_total_vmdk_size(vm_files)
                try:
                    free = shutil.disk_usage(output_dir).free
                except OSError:
                    free = 0
                messagebox.showerror("Error", self._t("error.disk_space",
                    vmdk_size=f"{vmdk_total / (1024**3):.1f}",
                    free_size=f"{free / (1024**3):.1f}"))
                return

        self.state = ConversionState(running=True, total=len(vm_files))
        self.view.clear_log()
        self.view.set_running(True)

        target_display = {"kvm": "KVM", "nutanix": "Nutanix AHV", "both": "KVM + Nutanix"}
        self.view.append_log(self._t("log.start", target=target_display.get(target, target)))
        self.view.append_log(self._t("log.found", count=len(vm_files)))
        self.view.append_log("")

        self._thread = threading.Thread(
            target=self._run_conversion,
            args=(input_dir, output_dir, options),
            daemon=True,
        )
        self._thread.start()

    def _run_conversion(self, input_dir: str, output_dir: str, options: ConversionOptions):
        def log_fn(msg_tuple):
            key, kwargs = msg_tuple
            text = self._t(key, **kwargs)
            self.view.root.after(0, self.view.append_log, text)

        def progress_fn(current, total):
            if total > 0:
                pct = (current / total) * 100
                self.view.root.after(0, self.view.progress_var.set, pct)
                if current < total:
                    status = self._t("status.converting",
                                     file=f"VM {current+1}",
                                     current=current+1, total=total)
                    self.view.root.after(0, self.view.status_var.set, status)

        try:
            results = self.converter.convert_all(
                input_dir, output_dir, options,
                log_fn=log_fn, progress_fn=progress_fn,
            )

            success = sum(1 for r in results if r.success)
            total = len(results)

            summary = self._t("log.complete", success=success, total=total)
            self.view.root.after(0, self.view.append_log, "")
            self.view.root.after(0, self.view.append_log, summary)

            # Log errors
            for r in results:
                if not r.success:
                    err_msg = self._t("log.error", message=f"{r.vm_name}: {r.error}")
                    self.view.root.after(0, self.view.append_log, err_msg)

            # Log output details
            for r in results:
                if r.success and r.config:
                    info_lines = [
                        f"",
                        f"  [{r.config.display_name}]",
                        f"    CPU: {r.config.num_cpus} vCPU ({r.config.cores_per_socket} cores/socket)",
                        f"    Memory: {r.config.memory_mb} MB",
                        f"    Disks: {len(r.config.disks)}",
                        f"    Networks: {len(r.config.networks)}",
                        f"    Firmware: {r.config.firmware.upper()}",
                    ]
                    if r.kvm_result:
                        info_lines.append(f"    KVM XML: {r.kvm_result['xml_path']}")
                        info_lines.append(f"    KVM Script: {r.kvm_result['import_script']}")
                    if r.nutanix_result:
                        info_lines.append(f"    Nutanix acli: {r.nutanix_result['acli_script']}")
                        info_lines.append(f"    Nutanix API: {r.nutanix_result['api_script']}")
                        info_lines.append(f"    Nutanix JSON: {r.nutanix_result['json_spec']}")
                    if not r.disk_converted and r.config.disks:
                        info_lines.append(f"    ** Disk conversion: manual (see scripts)")

                    for line in info_lines:
                        self.view.root.after(0, self.view.append_log, line)

            done_msg = self._t("status.done", success=success, total=total)
            self.view.root.after(0, self.view.status_var.set, done_msg)

        except Exception as e:
            err = self._t("status.error", message=str(e))
            self.view.root.after(0, self.view.status_var.set, err)
            self.view.root.after(0, self.view.append_log,
                                self._t("log.error", message=str(e)))

        finally:
            self.state.running = False
            self.view.root.after(0, self.view.set_running, False)

    def _stop_conversion(self):
        self.converter.stop()
        self.view.status_var.set(self._t("status.stopped"))
        self.view.set_running(False)
