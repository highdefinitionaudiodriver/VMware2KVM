"""
GUI View layer.
tkinterウィジェットの生成・配置・スタイリングのみを担当。
"""
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Callable, Dict

from .i18n import I18n, LANGUAGES
from .gui_model import TARGET_OPTIONS, DEFAULT_EXTENSIONS


class VMware2KVMView:
    """View: ウィジェットの生成・レイアウトのみ."""

    def __init__(self, root: tk.Tk, i18n: I18n):
        self.root = root
        self.i18n = i18n
        self.root.geometry("900x800")
        self.root.minsize(750, 650)
        self.root.resizable(True, True)

        self._widgets: Dict[str, ttk.Widget] = {}

        # tkinter variables
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.target_var = tk.StringVar(value="kvm")
        self.extensions_var = tk.StringVar(value=DEFAULT_EXTENSIONS)
        self.container_var = tk.StringVar(value="default-container")

        self.convert_disk_var = tk.BooleanVar(value=True)
        self.generate_config_var = tk.BooleanVar(value=True)
        self.generate_script_var = tk.BooleanVar(value=True)
        self.compress_var = tk.BooleanVar(value=True)
        self.thin_var = tk.BooleanVar(value=True)

        self.progress_var = tk.DoubleVar(value=0)
        self.status_var = tk.StringVar()

        # Language mapping
        lang_display = [f"{v}" for v in LANGUAGES.values()]
        lang_codes = list(LANGUAGES.keys())
        self._lang_code_map = dict(zip(lang_display, lang_codes))

        # Target mapping
        self._target_code_map: Dict[str, str] = {}

        self._setup_styles()
        self._build_ui()

    def _t(self, key: str, **kwargs) -> str:
        return self.i18n.t(key, **kwargs)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 14, "bold"), foreground="#2c3e50")
        style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Run.TButton", font=("Segoe UI", 10, "bold"))
        style.configure("TLabelframe.Label", font=("Segoe UI", 9, "bold"))

    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Top bar: Title + Language selector ---
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 10))

        self._widgets["title"] = ttk.Label(top_frame, style="Title.TLabel")
        self._widgets["title"].pack(side=tk.LEFT)

        lang_frame = ttk.Frame(top_frame)
        lang_frame.pack(side=tk.RIGHT)
        self._widgets["lang_label"] = ttk.Label(lang_frame)
        self._widgets["lang_label"].pack(side=tk.LEFT, padx=(0, 5))
        self._widgets["lang_combo"] = ttk.Combobox(
            lang_frame, values=list(self._lang_code_map.keys()),
            width=12, state="readonly"
        )
        self._widgets["lang_combo"].set(list(self._lang_code_map.keys())[0])
        self._widgets["lang_combo"].pack(side=tk.LEFT)

        # --- Directory selection ---
        dir_frame = ttk.LabelFrame(main_frame, padding=8)
        dir_frame.pack(fill=tk.X, pady=(0, 8))
        self._widgets["dir_frame"] = dir_frame

        # Input
        row_in = ttk.Frame(dir_frame)
        row_in.pack(fill=tk.X, pady=2)
        self._widgets["input_label"] = ttk.Label(row_in, width=25, anchor="w")
        self._widgets["input_label"].pack(side=tk.LEFT)
        ttk.Entry(row_in, textvariable=self.input_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._widgets["input_btn"] = ttk.Button(row_in)
        self._widgets["input_btn"].pack(side=tk.RIGHT)

        # Output
        row_out = ttk.Frame(dir_frame)
        row_out.pack(fill=tk.X, pady=2)
        self._widgets["output_label"] = ttk.Label(row_out, width=25, anchor="w")
        self._widgets["output_label"].pack(side=tk.LEFT)
        ttk.Entry(row_out, textvariable=self.output_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._widgets["output_btn"] = ttk.Button(row_out)
        self._widgets["output_btn"].pack(side=tk.RIGHT)

        # --- Target + Extensions ---
        mid_frame = ttk.Frame(main_frame)
        mid_frame.pack(fill=tk.X, pady=(0, 8))

        # Target
        target_frame = ttk.LabelFrame(mid_frame, padding=8)
        target_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        self._widgets["target_frame"] = target_frame

        self._widgets["target_combo"] = ttk.Combobox(
            target_frame, width=25, state="readonly"
        )
        self._widgets["target_combo"].pack(fill=tk.X)

        # Nutanix container (shown when target includes nutanix)
        container_row = ttk.Frame(target_frame)
        container_row.pack(fill=tk.X, pady=(4, 0))
        self._widgets["container_label"] = ttk.Label(container_row, text="Container:")
        self._widgets["container_label"].pack(side=tk.LEFT)
        ttk.Entry(container_row, textvariable=self.container_var, width=20).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4
        )

        # Extensions
        ext_frame = ttk.LabelFrame(mid_frame, padding=8)
        ext_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(4, 0))
        self._widgets["ext_frame"] = ext_frame
        ttk.Entry(ext_frame, textvariable=self.extensions_var).pack(fill=tk.X)

        # --- Options ---
        opt_frame = ttk.LabelFrame(main_frame, padding=8)
        opt_frame.pack(fill=tk.X, pady=(0, 8))
        self._widgets["opt_frame"] = opt_frame

        opts_left = ttk.Frame(opt_frame)
        opts_left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        opts_right = ttk.Frame(opt_frame)
        opts_right.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        self._widgets["chk_disk"] = ttk.Checkbutton(opts_left, variable=self.convert_disk_var)
        self._widgets["chk_disk"].pack(anchor="w")
        self._widgets["chk_config"] = ttk.Checkbutton(opts_left, variable=self.generate_config_var)
        self._widgets["chk_config"].pack(anchor="w")
        self._widgets["chk_script"] = ttk.Checkbutton(opts_left, variable=self.generate_script_var)
        self._widgets["chk_script"].pack(anchor="w")
        self._widgets["chk_compress"] = ttk.Checkbutton(opts_right, variable=self.compress_var)
        self._widgets["chk_compress"].pack(anchor="w")
        self._widgets["chk_thin"] = ttk.Checkbutton(opts_right, variable=self.thin_var)
        self._widgets["chk_thin"].pack(anchor="w")

        # --- Run / Stop buttons ---
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        self._widgets["run_btn"] = ttk.Button(btn_frame, style="Run.TButton")
        self._widgets["run_btn"].pack(side=tk.LEFT, padx=(0, 8))
        self._widgets["stop_btn"] = ttk.Button(btn_frame, state="disabled")
        self._widgets["stop_btn"].pack(side=tk.LEFT)

        # --- Progress bar ---
        self._widgets["progress"] = ttk.Progressbar(
            main_frame, variable=self.progress_var, maximum=100
        )
        self._widgets["progress"].pack(fill=tk.X, pady=(0, 4))

        # --- Status ---
        self._widgets["status"] = ttk.Label(main_frame, textvariable=self.status_var)
        self._widgets["status"].pack(fill=tk.X, pady=(0, 4))

        # --- Log area ---
        self._widgets["log"] = scrolledtext.ScrolledText(
            main_frame, height=16, font=("Consolas", 9), state="disabled",
            wrap=tk.WORD
        )
        self._widgets["log"].pack(fill=tk.BOTH, expand=True)

        self._apply_texts()

    def _apply_texts(self):
        t = self._t
        self.root.title(t("app.title"))
        self._widgets["title"].config(text=t("app.title"))
        self._widgets["lang_label"].config(text=t("label.language"))
        self._widgets["input_label"].config(text=t("label.input_dir"))
        self._widgets["output_label"].config(text=t("label.output_dir"))
        self._widgets["input_btn"].config(text=t("btn.browse"))
        self._widgets["output_btn"].config(text=t("btn.browse"))
        self._widgets["run_btn"].config(text=t("btn.run"))
        self._widgets["stop_btn"].config(text=t("btn.stop"))

        self._widgets["dir_frame"].config(text=t("label.input_dir").split("(")[0].strip())

        # Target combo
        self._target_code_map = {}
        target_displays = []
        for code, i18n_key in TARGET_OPTIONS.items():
            display = t(i18n_key)
            target_displays.append(display)
            self._target_code_map[display] = code
        self._widgets["target_combo"].config(values=target_displays)
        self._widgets["target_combo"].set(target_displays[0])
        self._widgets["target_frame"].config(text=t("label.target"))

        self._widgets["ext_frame"].config(text=t("label.extensions"))
        self._widgets["opt_frame"].config(text=t("label.options"))

        self._widgets["chk_disk"].config(text=t("opt.convert_disk"))
        self._widgets["chk_config"].config(text=t("opt.generate_config"))
        self._widgets["chk_script"].config(text=t("opt.generate_script"))
        self._widgets["chk_compress"].config(text=t("opt.compress_qcow2"))
        self._widgets["chk_thin"].config(text=t("opt.thin_provision"))

        self.status_var.set(t("status.ready"))

    def refresh_texts(self):
        self._apply_texts()

    def get_target_code(self) -> str:
        display = self._widgets["target_combo"].get()
        return self._target_code_map.get(display, "kvm")

    def get_lang_code(self) -> str:
        display = self._widgets["lang_combo"].get()
        return self._lang_code_map.get(display, "ja")

    def append_log(self, text: str):
        log_widget = self._widgets["log"]
        log_widget.config(state="normal")
        log_widget.insert(tk.END, text + "\n")
        log_widget.see(tk.END)
        log_widget.config(state="disabled")

    def clear_log(self):
        log_widget = self._widgets["log"]
        log_widget.config(state="normal")
        log_widget.delete("1.0", tk.END)
        log_widget.config(state="disabled")

    def set_running(self, running: bool):
        state_run = "disabled" if running else "normal"
        state_stop = "normal" if running else "disabled"
        self._widgets["run_btn"].config(state=state_run)
        self._widgets["stop_btn"].config(state=state_stop)

    def bind_event(self, widget_key: str, event: str, callback: Callable):
        self._widgets[widget_key].bind(event, callback)

    def bind_command(self, widget_key: str, callback: Callable):
        self._widgets[widget_key].config(command=callback)
