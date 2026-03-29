# VMware2KVM 操作説明書

**VMware → KVM / Nutanix AHV 移行ツール**

Version 1.1.0 | 2026-03-28

---

## 目次

1. [概要](#1-概要)
2. [動作環境](#2-動作環境)
3. [インストール](#3-インストール)
4. [GUI モードの使い方](#4-gui-モードの使い方)
5. [CLI モードの使い方](#5-cli-モードの使い方)
6. [ネットワークマッピング設定](#6-ネットワークマッピング設定)
7. [Windows VM の移行手順](#7-windows-vm-の移行手順)
8. [出力ファイルの説明](#8-出力ファイルの説明)
9. [移行後の作業](#9-移行後の作業)
10. [トラブルシューティング](#10-トラブルシューティング)
11. [制限事項・注意点](#11-制限事項注意点)

---

## 1. 概要

VMware2KVM は、VMware vSphere/Workstation の仮想マシン定義ファイルを解析し、
KVM (libvirt) および Nutanix AHV 向けの設定ファイル・移行スクリプトを自動生成するツールです。

### 対応する入力ファイル

| 形式 | 説明 |
|---|---|
| `.vmx` | VMware Workstation / ESXi 仮想マシン設定ファイル |
| `.ovf` | Open Virtualization Format (XML ベース) |
| `.ova` | OVF + VMDK の tar アーカイブ |

### 生成される出力

| ファイル | 対象 | 説明 |
|---|---|---|
| `{VM名}.xml` | KVM | libvirt ドメイン定義 XML |
| `import_{VM名}.sh` | KVM | qemu-img 変換 + virsh define スクリプト |
| `import_{VM名}_acli.sh` | Nutanix | acli コマンドベースのインポートスクリプト |
| `import_{VM名}_api.sh` | Nutanix | Prism Central REST API スクリプト |
| `{VM名}_spec.json` | Nutanix | Prism v3 API VM 仕様 JSON |
| `migration_report.csv` | 共通 | 一括変換結果のCSVレポート |
| `migration.log` | 共通 | 詳細ログ (MAC アドレス・NIC情報含む) |

---

## 2. 動作環境

### 必須

- **OS**: Windows 10/11, Linux (Ubuntu 20.04+, RHEL 8+, CentOS Stream 9+)
- **Python**: 3.9 以上 (exe 版は不要)

### 推奨

- **qemu-img**: ディスクイメージ変換に必要 (未インストール時はコマンド生成のみ)
- **virsh**: KVM へのインポートに必要 (移行先サーバーで実行)
- **acli / ncli**: Nutanix へのインポートに必要 (Nutanix CVM で実行)

### exe版の場合

- `VMware2KVM.exe` を任意のフォルダに配置するだけで使用可能
- `network_map.json` を exe と同じフォルダに配置すると自動読み込み

---

## 3. インストール

### exe版 (推奨)

1. `dist/VMware2KVM.exe` を任意のフォルダにコピー
2. 同フォルダに `input/` フォルダを作成
3. (任意) `network_map.json` を同フォルダに配置
4. `VMware2KVM.exe` をダブルクリックで起動

### Python版

```bash
pip install -r requirements.txt
python main.py
```

---

## 4. GUI モードの使い方

### 画面構成

```
┌──────────────────────────────────────────┐
│  VMware → KVM / Nutanix 移行ツール [言語]│
├──────────────────────────────────────────┤
│ 入力フォルダ: [____________] [参照...]   │
│ 出力フォルダ: [____________] [参照...]   │
├───────────────────┬──────────────────────┤
│ 変換先            │ 対象拡張子           │
│ [KVM (libvirt) ▼] │ [.vmx,.ovf,.ova]    │
│ Container: [____] │                      │
├───────────────────┴──────────────────────┤
│ 変換オプション                           │
│ [x] ディスクイメージ変換  [x] qcow2圧縮 │
│ [x] VM設定ファイル生成    [x] シンプロビ │
│ [x] インポートスクリプト生成             │
├──────────────────────────────────────────┤
│ [一括変換 実行]  [停止]                  │
│ [=============================] 75%      │
│ 変換中: VM 3/4                           │
├──────────────────────────────────────────┤
│ === VMware → KVM 変換開始 ===            │
│ 3 個のVMを検出                           │
│ --- VM変換開始: WebServer01 ---          │
│ libvirt XML生成中: WebServer01           │
│ VM変換完了: WebServer01                  │
│ ...                                      │
└──────────────────────────────────────────┘
```

### 操作手順

1. **入力フォルダ**: VMware ファイルが入ったフォルダを選択
2. **出力フォルダ**: 変換結果の出力先を選択
3. **変換先**: `KVM (libvirt)` / `Nutanix AHV` / `KVM + Nutanix 両方` から選択
4. **オプション**: 必要に応じて設定
5. **「一括変換 実行」** をクリック
6. ログエリアで進捗を確認
7. 完了後、出力フォルダを確認

### 言語切替

右上のドロップダウンで `日本語` / `English` を切り替え可能。

---

## 5. CLI モードの使い方

### 基本コマンド

```bash
# KVM のみ (設定ファイル生成のみ、ディスク変換なし)
python main.py -i ./input -o ./output -t kvm --no-disk

# Nutanix のみ
python main.py -i ./input -o ./output -t nutanix --no-disk

# 両方に変換
python main.py -i ./input -o ./output -t both --no-disk

# ディスク変換あり (qemu-img が必要)
python main.py -i ./input -o ./output -t kvm

# ネットワークマッピング指定
python main.py -i ./input -o ./output -t both --network-map ./network_map.json

# Windows BSOD フォールバック無効化 (上級者向け)
python main.py -i ./input -o ./output -t kvm --no-win-fallback

# virtio-win.iso パス指定
python main.py -i ./input -o ./output -t kvm --virtio-iso /path/to/virtio-win.iso
```

### 全オプション一覧

```
--input, -i          入力フォルダ (必須)
--output, -o         出力フォルダ (必須)
--target, -t         変換先: kvm / nutanix / both (default: kvm)
--ext                対象拡張子 (default: .vmx,.ovf,.ova)
--no-disk            ディスク変換をスキップ
--no-compress        qcow2 圧縮を無効化
--container          Nutanix コンテナ名 (default: default-container)
--network-map        network_map.json のパス
--no-win-fallback    Windows SATA/IDE フォールバック無効化
--virtio-iso         virtio-win.iso のパス
--lang               言語: ja / en (default: ja)
--gui                GUI モードを強制
```

---

## 6. ネットワークマッピング設定

### network_map.json の構成

exe と同じフォルダ、またはプロジェクトルートに `network_map.json` を配置すると自動的に読み込まれます。

```json
{
  "kvm": {
    "VMwareのネットワーク名": {
      "type": "bridge または network",
      "name": "KVMのブリッジ名またはネットワーク名"
    }
  },
  "nutanix": {
    "VMwareのネットワーク名": {
      "subnet_name": "Nutanixのサブネット名",
      "subnet_uuid": "サブネットUUID",
      "vlan_id": 100
    }
  }
}
```

### 設定例

```json
{
  "kvm": {
    "VM Network":          { "type": "bridge",  "name": "br0" },
    "Production Network":  { "type": "bridge",  "name": "br-prod" },
    "Management Network":  { "type": "network", "name": "management" }
  },
  "nutanix": {
    "VM Network":          { "subnet_name": "vm-subnet",   "subnet_uuid": "abc-123", "vlan_id": 0 },
    "Production Network":  { "subnet_name": "prod-subnet", "subnet_uuid": "def-456", "vlan_id": 100 }
  }
}
```

### マッピングされない場合

- **KVM**: `<source network="default"/>` (NAT) がデフォルト
- **Nutanix**: `<SUBNET_UUID>` プレースホルダーが使用される

---

## 7. Windows VM の移行手順

Windows VM は VMware 専用ドライバで動作しているため、そのまま KVM に移行すると
**BSOD (Blue Screen of Death)** が発生します。本ツールはこれを自動回避します。

### 自動で行われる対策

| 対策 | 説明 |
|---|---|
| ディスクバス変更 | `virtio` → `sata` (EFI) / `ide` (BIOS) にフォールバック |
| virtio-win.iso マウント | CD-ROM として自動マウント |
| Hyper-V 最適化 | `hyperv enlightenments` を XML に追加 |
| Clock 設定 | `localtime` + `hypervclock` |

### 移行後の手順 (KVM)

1. `virsh start {VM名}` で VM を起動
2. Windows にログイン
3. CD-ROM ドライブ (D: 等) を開く
4. 以下のドライバをインストール:
   - `viostor` (ストレージ) または `vioscsi`
   - `NetKVM` (ネットワーク)
   - `Balloon` (メモリバルーン)
   - `vioserial` (シリアルポート)
5. `virsh edit {VM名}` でディスクバスを `sata` → `virtio` に変更
6. VM を再起動

### virtio-win.iso の入手

```bash
# RHEL/CentOS
sudo yum install virtio-win

# Ubuntu
# https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/
```

---

## 8. 出力ファイルの説明

### KVM: libvirt XML (`{VM名}.xml`)

```xml
<domain type="kvm">
  <name>WebServer01</name>
  <memory unit="KiB">4194304</memory>
  <vcpu>4</vcpu>
  <devices>
    <disk type="file" device="disk">
      <source file="/path/to/WebServer01-disk0.qcow2"/>
      <target dev="vda" bus="virtio"/>
    </disk>
    <interface type="bridge">
      <source bridge="br0"/>
      <mac address="00:50:56:8a:12:34"/>  ← MAC維持
    </interface>
  </devices>
</domain>
```

### Nutanix: VM Spec JSON (`{VM名}_spec.json`)

```json
{
  "spec": {
    "name": "WebServer01",
    "resources": {
      "num_sockets": 2,
      "num_vcpus_per_socket": 2,
      "memory_size_mib": 4096,
      "disk_list": [...],
      "nic_list": [
        {
          "mac_address": "00:50:56:8a:12:34",  ← MAC維持
          "subnet_reference": { "uuid": "..." }
        }
      ]
    }
  }
}
```

### migration_report.csv

| VM Name | Status | CPU | Memory (MB) | Disks | Elapsed (sec) | Error |
|---|---|---|---|---|---|---|
| WebServer01 | OK | 4 | 4096 | 1 | 0.02 | |
| DBServer01 | OK | 8 | 16384 | 2 | 0.03 | |
| FailedVM | NG | | | | 0.01 | Parse error |

### migration.log

各 VM の詳細情報（CPU/メモリ/NIC/MACアドレス/出力パス）をテキスト形式で記録。

---

## 9. 移行後の作業

### KVM の場合

```bash
# 1. ディスク変換 (qemu-img)
qemu-img convert -f vmdk -O qcow2 -c "source.vmdk" "target.qcow2"

# 2. VM を libvirt に登録
virsh define /path/to/VM.xml

# 3. VM を起動
virsh start VM名

# 4. (任意) 自動起動を有効化
virsh autostart VM名
```

または、生成された `import_{VM名}.sh` を実行：

```bash
bash import_WebServer01.sh
```

### Nutanix の場合

```bash
# 生成された acli スクリプトを Nutanix CVM で実行
bash import_WebServer01_acli.sh

# または API スクリプトを実行
bash import_WebServer01_api.sh
```

**JSON spec を使う場合**: Prism Central UI から「VM > Import」で JSON ファイルを指定。

---

## 10. トラブルシューティング

### qemu-img が見つからない

```
[エラー] qemu-img が見つかりません。コマンド生成のみ行います。
```

**対処**: `--no-disk` オプションで設定ファイルのみ生成し、移行先サーバーで手動変換。

```bash
# 移行先サーバーで実行
qemu-img convert -f vmdk -O qcow2 -c source.vmdk target.qcow2
```

### ディスク容量不足

```
[エラー] 容量不足! VMDK合計 120.5 GB > 空き 80.2 GB。処理を中断します。
```

**対処**: 出力先のディスク空き容量を確保するか、`--no-disk` でスキップ。

### Windows VM が BSOD になる

**対処**:
1. XML のディスクバスが `sata` / `ide` であることを確認
2. virtio-win.iso がマウントされていることを確認
3. `--no-win-fallback` を使っていないことを確認

### OVA ファイルの解析エラー

**対処**: OVA を手動展開して .ovf + .vmdk に分離してから入力フォルダに配置。

```bash
tar xvf server.ova -C ./input/server/
```

---

## 11. 制限事項・注意点

| 項目 | 説明 |
|---|---|
| **VMware Tools** | 移行後は VMware Tools をアンインストールし、`qemu-guest-agent` (KVM) または `Nutanix Guest Tools` をインストールしてください |
| **スナップショット** | VMware スナップショットチェーンは未対応。移行前にスナップショットを統合してください |
| **RDM / パススルーデバイス** | Raw Device Mapping やPCIパススルーは変換対象外です |
| **vGPU** | VMware vGPU 設定は移行されません |
| **ライセンス** | Windows ライセンスの再認証が必要になる場合があります |
| **ネットワーク設定** | VM 内部の IP アドレス設定は変更されません。必要に応じて手動で変更してください |
| **パフォーマンス** | 大容量 VMDK の変換には相応の時間がかかります (1TB ≒ 30-60分 程度) |
| **ESXi 直接接続** | 本ツールはエクスポート済みファイルを変換します。ESXi への直接接続機能はありません |

---

*Generated with Claude Code - VMware2KVM v1.1.0*
