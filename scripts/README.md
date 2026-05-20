# scripts/ — 補助ツール

メイン変換パイプラインに依存せず実行できる、見積もり・診断用の補助スクリプト集。

---

## `diagnose.py` — VMware → KVM / Nutanix 移行 事前診断

入力ディレクトリの `.vmx` / `.ovf` を走査し、変換せず以下を出力：

- 各 VM の **AUTO / REVIEW / MANUAL** 分類
- 移行を阻む構成のランキング Top 10
- 合計 vCPU / メモリ / ディスク数の集計
- 概算工数（時間／人日）
- A4 1〜2 枚の HTML サマリ

> 💡 これは何の役に立つのか：
> Broadcom 買収後の VMware ライセンス高騰に対応するため、自社の VMware 環境を
> KVM/Nutanix に移行する初期見積もりを **5 分で 1 ページの数字**に変えます。

### 使い方

```bash
# CSV のみ
python scripts/diagnose.py /path/to/vmware_export

# HTML サマリも生成
python scripts/diagnose.py /path/to/vmware_export --html report.html
```

出力例：

```
走査中: 47 VM...
[OK] CSV: /work/estimate.csv

=== 集計 ===
  AUTO   : 28 VM
  REVIEW : 14 VM
  MANUAL : 5 VM
  合計リソース: 312 vCPU / 1024.0 GB / 89 ディスク
  概算工数: 87.5 時間 (≒ 10.9 人日)

  移行阻害 Top 5:
    - VMware ポートグループ名 → KVM 側のネットワーク定義に対応表が必要: 47
    - VMDK ディスク → qemu-img で qcow2/raw に変換が必要: 89
    - vSAN 統合 → Ceph / Gluster / Nutanix DSF への完全置換: 12
    - VM 暗号化 → KMS 再構築 + 復号して再暗号化: 3
    - SR-IOV → ホスト NIC + IOMMU 再構築: 2
```

### 判定軸

| カテゴリ | 含むもの | 推定工数 |
|---|---|---|
| **AUTO** | 標準 SCSI / e1000 / vmxnet3 NIC / EFI / 標準ゲスト OS | 1 分/件 |
| **REVIEW** | BusLogic / カスタムネットワーク / VMware Tools / NUMA / CPU トポロジ / スナップショット | 2-3 分/件 |
| **MANUAL** | vSAN / FT / SR-IOV / vGPU / PCI Passthrough / VM 暗号化 / SGX | 3-5 分/件 |

ファイル単位：
- MANUAL が 1 つでもあれば **MANUAL**
- REVIEW があれば **REVIEW**
- それ以外は **AUTO**

### 出力 CSV のスキーマ

```
relative_path, vm_name, guest_os, memory_mb, num_cpus,
disk_count, nic_count, loc, category,
auto_hits, review_hits, manual_hits,
estimated_effort_minutes, top_findings
```

UTF-8 BOM 付き / CRLF（Excel 文字化け回避）

### virt-v2v との違い

| 観点 | virt-v2v / VMware Converter | 本ツール |
|---|---|---|
| 用途 | 単一 VM の実変換 | **複数 VM の事前棚卸し・見積もり** |
| 入力 | ライブ VMware/ESXi 接続 or .ova/.ovf | **.vmx メタデータのみ** |
| 出力 | 変換後の VM イメージ | **CSV + HTML レポート** |
| 規模 | 1 VM ずつ | 数百 VM 一括 |

→ 本ツールは「virt-v2v の代替」ではなく「**virt-v2v を実行する前の見積もり**」用です。

### 商用利用

- 個人・社内 PoC は無料（MIT）
- 自社 VMware 環境の **移行アセスメント受託**（A4 PDF 納品 + 推奨移行戦略 + ネットワーク対応表）は応相談
- Nutanix / Proxmox / OpenStack 等への特化対応も応相談
- 連絡先: highdefinitionaudiodriver@gmail.com
