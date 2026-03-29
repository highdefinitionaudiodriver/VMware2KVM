# VMware2KVM

**VMware → KVM / Nutanix AHV Migration Tool**

VMware vSphere 環境の仮想マシン (.vmx / .ovf / .ova) を、KVM (libvirt) および Nutanix AHV へ一括変換するツールです。
フォルダに VMware ファイルを入れて実行するだけで、libvirt XML / Nutanix acli スクリプト / Prism API JSON を自動生成します。

> VMware ライセンス高騰に伴う KVM / Nutanix 移行を支援するために開発されました。

---

## Features

| Feature | Description |
|---|---|
| **一括変換** | input フォルダ内の全 VM を一括でスキャン・変換 |
| **GUI / CLI 両対応** | tkinter GUI またはコマンドラインで実行可能 |
| **KVM (libvirt) 出力** | libvirt XML + qemu-img 変換コマンド + import シェルスクリプト |
| **Nutanix AHV 出力** | acli スクリプト + Prism Central REST API スクリプト + VM Spec JSON |
| **Windows BSOD 回避** | Windows VM は自動的に SATA/IDE バスにフォールバック + virtio-win.iso マウント |
| **ネットワークマッピング** | `network_map.json` で VMware ポートグループ → KVM ブリッジ / Nutanix サブネットを変換 |
| **MAC アドレス維持** | VMware の MAC アドレスを移行先に自動引き継ぎ |
| **Pre-flight Check** | 変換前にディスク空き容量を自動チェック |
| **移行レポート** | `migration_report.csv` + `migration.log` を自動出力 |
| **多言語対応** | 日本語 / English |

---

## Architecture

```
VMware2KVM/
├── main.py                    # Entry point (GUI/CLI)
├── network_map.json           # Network mapping config
├── requirements.txt
├── build.bat / build.sh       # PyInstaller build scripts
├── src/
│   ├── vmx_parser.py          # VMware .vmx parser
│   ├── ovf_parser.py          # OVF/OVA parser
│   ├── kvm_generator.py       # KVM libvirt XML generator
│   ├── nutanix_generator.py   # Nutanix acli/API/JSON generator
│   ├── converter.py           # Conversion orchestrator + report
│   ├── gui_model.py           # MVC - Model
│   ├── gui_view.py            # MVC - View (tkinter)
│   ├── gui_controller.py      # MVC - Controller
│   └── i18n.py                # Internationalization (ja/en)
├── input/                     # Drop VMware files here
└── output/                    # Converted files output here
```

---

## Quick Start

### GUI Mode

```bash
python main.py
```

または配布用 exe を実行：

```
VMware2KVM.exe
```

### CLI Mode

```bash
# KVM + Nutanix 両方に変換 (ディスク変換はスキップ)
python main.py --input ./input --output ./output --target both --no-disk

# KVM のみ、ディスク変換あり
python main.py --input ./input --output ./output --target kvm

# Nutanix のみ、英語表示
python main.py --input ./input --output ./output --target nutanix --lang en
```

---

## Usage

### 1. 入力フォルダに VMware ファイルを配置

```
input/
├── WebServer01/
│   ├── WebServer01.vmx
│   └── WebServer01.vmdk
├── DBServer01/
│   ├── DBServer01.vmx
│   ├── DBServer01-os.vmdk
│   └── DBServer01-data.vmdk
└── AppServer.ova
```

**対応フォーマット**: `.vmx`, `.ovf`, `.ova`

### 2. 変換を実行

GUI の「一括変換 実行」ボタンを押すか、CLI で `python main.py -i ./input -o ./output` を実行。

### 3. 出力結果を確認

```
output/
├── WebServer01/
│   ├── WebServer01.xml              # libvirt XML
│   ├── import_WebServer01.sh        # KVM import script
│   ├── import_WebServer01_acli.sh   # Nutanix acli script
│   ├── import_WebServer01_api.sh    # Nutanix API script
│   └── WebServer01_spec.json        # Nutanix VM spec
├── DBServer01/
│   └── ...
├── migration_report.csv             # CSV report
└── migration.log                    # Detailed log
```

---

## CLI Options

| Option | Default | Description |
|---|---|---|
| `--input`, `-i` | - | 入力フォルダ (VMware ファイル) |
| `--output`, `-o` | - | 出力フォルダ |
| `--target`, `-t` | `kvm` | 変換先: `kvm`, `nutanix`, `both` |
| `--ext` | `.vmx,.ovf,.ova` | 対象拡張子 |
| `--no-disk` | false | ディスク変換スキップ (設定ファイルのみ生成) |
| `--no-compress` | false | qcow2 圧縮を無効化 |
| `--container` | `default-container` | Nutanix コンテナ名 |
| `--network-map` | auto | `network_map.json` のパス |
| `--no-win-fallback` | false | Windows SATA/IDE フォールバックを無効化 |
| `--virtio-iso` | auto | virtio-win.iso のパス |
| `--lang` | `ja` | 言語: `ja`, `en` |
| `--gui` | false | GUI モードを強制 |

---

## Network Mapping

`network_map.json` を編集して、VMware ネットワーク名を KVM / Nutanix のネットワークにマッピングします：

```json
{
  "kvm": {
    "VM Network": {
      "type": "bridge",
      "name": "br0"
    },
    "Production Network": {
      "type": "bridge",
      "name": "br-prod"
    }
  },
  "nutanix": {
    "VM Network": {
      "subnet_name": "vm-network-subnet",
      "subnet_uuid": "<SUBNET_UUID>",
      "vlan_id": 0
    }
  }
}
```

---

## Windows VM Migration

Windows VM の移行時は自動的に以下の対策を行います：

1. **ディスクバス**: SATA (EFI) / IDE (BIOS) にフォールバック → BSOD 回避
2. **virtio-win.iso**: CD-ROM として自動マウント
3. **Hyper-V Enlightenments**: `hyperv` 機能を XML に追加
4. **Clock**: `localtime` + `hypervclock` を設定

**移行後の手順**:
1. VM を起動
2. virtio-win.iso から VirtIO ドライバをインストール (viostor, NetKVM, Balloon)
3. XML を編集してディスクバスを `virtio` に変更
4. VM を再起動 → パフォーマンス向上

---

## Build (exe)

### Windows

```bash
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --windowed --name VMware2KVM --add-data "network_map.json;." main.py
```

出力: `dist/VMware2KVM.exe`

### Linux

```bash
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --name VMware2KVM --add-data "network_map.json:." main.py
```

---

## Requirements

- Python 3.9+
- `lxml` (OVF/OVA parsing)
- `qemu-img` (ディスク変換時のみ。未インストールの場合はコマンド生成のみ)
- `tkinter` (GUI 使用時)

---

## Conversion Flow

```
[VMware .vmx/.ovf/.ova]
        │
        ▼
   ┌─────────────┐
   │  VMX Parser  │  ← .vmx 設定ファイル解析
   │  OVF Parser  │  ← .ovf/.ova XML 解析
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │  VMConfig    │  ← 統一データモデル (CPU/Memory/Disk/Network)
   └──────┬──────┘
          │
     ┌────┴────┐
     ▼         ▼
┌─────────┐ ┌──────────────┐
│ KVM Gen │ │ Nutanix Gen  │
└────┬────┘ └──────┬───────┘
     ▼              ▼
  XML + .sh     acli + API + JSON
     │              │
     └──────┬───────┘
            ▼
    migration_report.csv
    migration.log
```

---

## License

MIT License

---

## Author

Generated with Claude Code
