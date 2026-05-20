#!/usr/bin/env python3
"""
VMware → KVM/Nutanix AHV 移行 事前診断スクリプト

VMware ライセンス高騰（Broadcom 買収後）に対応するため、自社の VMware 環境を
KVM / Nutanix AHV に移行する際の事前見積もりを作るための診断ツール。

入力ディレクトリの `.vmx` / `.ovf` / `.vmdk` 関連ファイルを走査し、
VM 単位で移行可能性をスコアリングします：

  - 各 VM を AUTO / REVIEW / MANUAL に分類
  - 移行を阻むパターン Top 10（NVRAM / PCI passthrough / vSAN / DVS 等）
  - 概算工数（時間／人日）
  - HTML サマリ（A4 1〜2 枚）

使い方:
    python scripts/diagnose.py <vmware_export_dir>          # report.csv
    python scripts/diagnose.py <vmware_export_dir> --html r.html
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────
# 判定ルール
#
# 単一の VMX/OVF ファイル単位で評価。
# AUTO: virt-v2v / virt-install で素直に変換可能
# REVIEW: 設定の手当てが必要（ネットワーク・ストレージ）
# MANUAL: 専用 HW / 商用拡張依存で代替実装が必要
# ──────────────────────────────────────────────────────────────────────────

AUTO_PATTERNS = [
    (r'^guestOS\s*=', 1, "guestOS 指定 → libvirt 互換 OS タイプにマッピング"),
    (r'^memSize\s*=', 1, "memSize → libvirt memory への単純コピー"),
    (r'^numvcpus\s*=', 1, "numvcpus → libvirt vcpu への単純コピー"),
    (r'^displayName\s*=', 1, "displayName → libvirt name に流用"),
    (r'^scsi[0-9]+\.virtualDev\s*=\s*"(lsisas1068|lsilogic|pvscsi)"',
     1, "標準 SCSI コントローラ → virtio へ自動置換"),
    (r'^ethernet[0-9]+\.virtualDev\s*=\s*"(e1000|e1000e|vmxnet3)"',
     1, "標準 NIC モデル → virtio へ自動置換可"),
    (r'^firmware\s*=\s*"efi"', 1, "EFI ファームウェア → OVMF で互換"),
]

REVIEW_PATTERNS = [
    (r'^scsi[0-9]+\.virtualDev\s*=\s*"buslogic"', 3,
     "BusLogic コントローラ → 古い OS のみ、Linux ドライバ要確認"),
    (r'^ide[0-9]+:[0-9]+\.fileName\s*=', 2,
     "IDE デバイス → 大半 OK だが boot 順序のテスト必要"),
    (r'^ethernet[0-9]+\.networkName\s*=', 2,
     "VMware ポートグループ名 → KVM 側のネットワーク定義に対応表が必要"),
    (r'^ethernet[0-9]+\.connectionType\s*=\s*"custom"', 3,
     "カスタムネットワーク → 個別マッピング要"),
    (r'^toolsInstallType\s*=', 2,
     "VMware Tools → KVM 側で qemu-guest-agent / virtio drivers 要再インストール"),
    (r'^cpuid\.coresPerSocket\s*=', 2,
     "CPU トポロジ指定 → libvirt topology に明示マッピング"),
    (r'^scsi[0-9]+:[0-9]+\.fileName\s*=\s*".*\.vmdk"', 2,
     "VMDK ディスク → qemu-img で qcow2/raw に変換が必要"),
    (r'^numa\.\w+\s*=', 3,
     "NUMA 指定 → ホスト構成に依存、libvirt numatune で再現"),
    (r'^sched\.cpu\.\w+\s*=', 2,
     "CPU スケジューラ指定 → libvirt cputune で再現"),
    (r'^snapshot\.\w+\s*=', 3,
     "スナップショット情報 → 移行前に統合 (consolidate) 推奨"),
]

MANUAL_PATTERNS = [
    (r'^pciPassthru[0-9]+\.\w+', 5,
     "PCI Passthrough → ホスト依存。IOMMU 設定の再構築が必要"),
    (r'^sgx\.\w+', 4,
     "SGX (Software Guard Extensions) → ホスト CPU 依存"),
    (r'^vmci0\.\w+', 3,
     "VMCI (VMware Communication Interface) → 互換なし、アプリ依存"),
    (r'^vsphereClient\.\w+', 2,
     "vSphere Client 固有設定 → 廃棄対象"),
    (r'^vsan\.\w+', 5,
     "vSAN 統合 → Ceph / Gluster / Nutanix DSF への完全置換"),
    (r'^encryption\.\w+\s*=\s*"TRUE"', 4,
     "VM 暗号化 → KMS 再構築 + 復号して再暗号化"),
    (r'^fault[Tt]olerance\.\w+', 5,
     "Fault Tolerance (FT) → KVM 互換機能なし、HA 設計に変更"),
    (r'^sriov\.\w+', 4,
     "SR-IOV → ホスト NIC + IOMMU 再構築"),
    (r'^vGPU\.\w+|^gpu\..*passthrough', 4,
     "vGPU / GPU Passthrough → NVIDIA vGPU ライセンス見直し + ホスト再構成"),
    (r'^nvram\s*=\s*".*\.nvram"', 3,
     "NVRAM ファイル → EFI 変数の手動移行が必要"),
    (r'^migrate\.hostlog\s*=', 3,
     "vMotion ホストログ → 移行時には不要（手動削除）"),
    (r'^pvscsi\.cmd\.\w+', 3,
     "PVSCSI 拡張コマンド → virtio-scsi では機能制限"),
]


@dataclass
class VMDiagnostic:
    path: str
    relative_path: str
    loc: int
    vm_name: str = ""
    guest_os: str = ""
    memory_mb: int = 0
    num_cpus: int = 0
    disk_count: int = 0
    nic_count: int = 0
    auto_hits: int = 0
    review_hits: int = 0
    manual_hits: int = 0
    weighted_effort_min: float = 0.0
    category: str = "AUTO"
    top_findings: list[tuple[str, int]] = field(default_factory=list)


def read_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="latin-1", errors="replace")


def extract_metadata(text: str) -> dict:
    """vmx から VM の基本属性を抽出"""
    meta = {"vm_name": "", "guest_os": "", "memory_mb": 0, "num_cpus": 0,
            "disk_count": 0, "nic_count": 0}
    m = re.search(r'^displayName\s*=\s*"([^"]*)"', text, re.MULTILINE)
    if m:
        meta["vm_name"] = m.group(1)
    m = re.search(r'^guestOS\s*=\s*"([^"]*)"', text, re.MULTILINE)
    if m:
        meta["guest_os"] = m.group(1)
    m = re.search(r'^memSize\s*=\s*"?(\d+)"?', text, re.MULTILINE)
    if m:
        meta["memory_mb"] = int(m.group(1))
    m = re.search(r'^numvcpus\s*=\s*"?(\d+)"?', text, re.MULTILINE)
    if m:
        meta["num_cpus"] = int(m.group(1))
    meta["disk_count"] = len(re.findall(r'\.fileName\s*=\s*".*\.vmdk"', text))
    meta["nic_count"] = len(re.findall(r'^ethernet\d+\.present\s*=\s*"TRUE"',
                                        text, re.MULTILINE))
    return meta


def diagnose_file(path: Path, root: Path) -> VMDiagnostic:
    raw = read_text(path)
    loc = raw.count("\n") + 1
    meta = extract_metadata(raw)
    findings: Counter[str] = Counter()
    effort = 0.0
    auto_hits = review_hits = manual_hits = 0

    for regex, w, desc in AUTO_PATTERNS:
        n = len(re.findall(regex, raw, re.MULTILINE | re.IGNORECASE))
        if n:
            auto_hits += n
            effort += n * w
            findings[desc] += n
    for regex, w, desc in REVIEW_PATTERNS:
        n = len(re.findall(regex, raw, re.MULTILINE | re.IGNORECASE))
        if n:
            review_hits += n
            effort += n * w
            findings[desc] += n
    for regex, w, desc in MANUAL_PATTERNS:
        n = len(re.findall(regex, raw, re.MULTILINE | re.IGNORECASE))
        if n:
            manual_hits += n
            effort += n * w
            findings[desc] += n

    if manual_hits > 0:
        category = "MANUAL"
    elif review_hits > 0:
        category = "REVIEW"
    else:
        category = "AUTO"

    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)

    return VMDiagnostic(
        path=str(path),
        relative_path=rel,
        loc=loc,
        vm_name=meta["vm_name"],
        guest_os=meta["guest_os"],
        memory_mb=meta["memory_mb"],
        num_cpus=meta["num_cpus"],
        disk_count=meta["disk_count"],
        nic_count=meta["nic_count"],
        auto_hits=auto_hits,
        review_hits=review_hits,
        manual_hits=manual_hits,
        weighted_effort_min=round(effort, 1),
        category=category,
        top_findings=findings.most_common(5),
    )


def collect_files(root: Path) -> list[Path]:
    exts = {".vmx", ".VMX", ".ovf", ".OVF"}
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in exts)


def write_csv(diags: list[VMDiagnostic], out_path: Path) -> None:
    headers = [
        "relative_path", "vm_name", "guest_os", "memory_mb", "num_cpus",
        "disk_count", "nic_count", "loc", "category",
        "auto_hits", "review_hits", "manual_hits",
        "estimated_effort_minutes", "top_findings",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(headers)
        for d in diags:
            top = "; ".join(f"{n}×{c}" for n, c in d.top_findings)
            w.writerow([
                d.relative_path, d.vm_name, d.guest_os, d.memory_mb,
                d.num_cpus, d.disk_count, d.nic_count, d.loc, d.category,
                d.auto_hits, d.review_hits, d.manual_hits,
                d.weighted_effort_min, top,
            ])


def aggregate(diags: list[VMDiagnostic]) -> dict:
    by_cat = Counter(d.category for d in diags)
    total_min = sum(d.weighted_effort_min for d in diags)
    all_findings: Counter[str] = Counter()
    for d in diags:
        for name, n in d.top_findings:
            all_findings[name] += n
    return {
        "vm_count": len(diags),
        "by_category": dict(by_cat),
        "total_memory_gb": round(sum(d.memory_mb for d in diags) / 1024.0, 1),
        "total_vcpus": sum(d.num_cpus for d in diags),
        "total_disks": sum(d.disk_count for d in diags),
        "total_effort_min": round(total_min, 1),
        "total_effort_hr": round(total_min / 60.0, 1),
        "total_effort_pd": round(total_min / 60.0 / 8.0, 1),
        "top_unsupported": all_findings.most_common(10),
    }


def write_html(diags: list[VMDiagnostic], out_path: Path) -> None:
    agg = aggregate(diags)
    by = agg["by_category"]
    auto_c = by.get("AUTO", 0)
    review_c = by.get("REVIEW", 0)
    manual_c = by.get("MANUAL", 0)
    n = max(1, agg["vm_count"])

    def pct(c: int) -> str:
        return f"{c / n * 100:.1f}"

    top_rows = "".join(
        f"<tr><td>{i + 1}</td><td>{html.escape(name)}</td><td>{count}</td></tr>"
        for i, (name, count) in enumerate(agg["top_unsupported"])
    )

    detail_rows = "".join(
        f"<tr><td>{html.escape(d.vm_name or d.relative_path)}</td>"
        f"<td>{html.escape(d.guest_os)}</td>"
        f"<td>{d.num_cpus} / {d.memory_mb//1024 if d.memory_mb else 0} GB</td>"
        f"<td class='cat-{d.category.lower()}'><strong>{d.category}</strong></td>"
        f"<td>{d.weighted_effort_min:.0f} 分</td>"
        f"<td>{html.escape('; '.join(f'{nm}×{cn}' for nm, cn in d.top_findings))}</td></tr>"
        for d in sorted(diags, key=lambda x: x.weighted_effort_min, reverse=True)[:20]
    )

    body = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8"><title>VMware → KVM / Nutanix 移行 事前診断レポート</title>
<style>
  body {{ font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif; max-width: 980px; margin: 20px auto; padding: 0 18px; color: #222; }}
  h1 {{ font-size: 22px; border-bottom: 3px solid #7c4dff; padding-bottom: 6px; }}
  h2 {{ font-size: 16px; margin-top: 28px; color: #7c4dff; }}
  .kpi {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }}
  .kpi-box {{ padding: 14px; background: #f5f5f5; border-radius: 6px; text-align: center; }}
  .kpi-box .big {{ font-size: 22px; font-weight: bold; }}
  .kpi-box .label {{ font-size: 11px; color: #666; margin-top: 2px; }}
  .cat-auto {{ color: #2e7d32; }}
  .cat-review {{ color: #ef6c00; }}
  .cat-manual {{ color: #c62828; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
  th {{ background: #fafafa; }}
  .summary-bar {{ height: 24px; display: flex; margin: 8px 0 16px; border-radius: 4px; overflow: hidden; font-size: 11px; color: #fff; text-align: center; line-height: 24px; }}
  .seg-auto {{ background: #4caf50; }}
  .seg-review {{ background: #ff9800; }}
  .seg-manual {{ background: #e53935; }}
  .alert {{ background: #ede7f6; border-left: 4px solid #7c4dff; padding: 12px; margin: 16px 0; font-size: 13px; }}
  .meta {{ font-size: 11px; color: #888; margin-top: 24px; padding-top: 12px; border-top: 1px solid #eee; }}
</style></head><body>
<h1>VMware → KVM / Nutanix 移行 事前診断レポート</h1>

<div class="alert">
  💸 <strong>Broadcom 買収後の VMware ライセンス高騰</strong>に対応するための初期見積もりレポートです。
  各 VM を移行可能性で 3 段階に分類しました。
</div>

<div class="kpi">
  <div class="kpi-box"><div class="big">{agg['vm_count']}</div><div class="label">対象 VM 数</div></div>
  <div class="kpi-box"><div class="big">{agg['total_vcpus']}</div><div class="label">合計 vCPU</div></div>
  <div class="kpi-box"><div class="big">{agg['total_memory_gb']:.1f}</div><div class="label">合計メモリ (GB)</div></div>
  <div class="kpi-box"><div class="big">{agg['total_effort_pd']}</div><div class="label">概算工数 (人日)</div></div>
</div>

<h2>変換可否の分布</h2>
<div class="summary-bar">
  <div class="seg-auto" style="width: {pct(auto_c)}%">AUTO {auto_c}</div>
  <div class="seg-review" style="width: {pct(review_c)}%">REVIEW {review_c}</div>
  <div class="seg-manual" style="width: {pct(manual_c)}%">MANUAL {manual_c}</div>
</div>
<table>
  <thead><tr><th>カテゴリ</th><th>意味</th><th>VM 数</th><th>構成比</th></tr></thead>
  <tbody>
    <tr><td class="cat-auto"><strong>AUTO</strong></td><td>virt-v2v / qemu-img で素直に変換可能。</td><td>{auto_c}</td><td>{pct(auto_c)}%</td></tr>
    <tr><td class="cat-review"><strong>REVIEW</strong></td><td>ネットワーク・ストレージ・VMware Tools 等で手当て必要。</td><td>{review_c}</td><td>{pct(review_c)}%</td></tr>
    <tr><td class="cat-manual"><strong>MANUAL</strong></td><td>vSAN / FT / SR-IOV / vGPU / PCI Passthrough 等、再設計必要。</td><td>{manual_c}</td><td>{pct(manual_c)}%</td></tr>
  </tbody>
</table>

<h2>移行を阻む構成 Top 10</h2>
<table>
  <thead><tr><th>#</th><th>パターン</th><th>検出件数</th></tr></thead>
  <tbody>{top_rows or '<tr><td colspan="3">該当なし</td></tr>'}</tbody>
</table>

<h2>工数集中 VM Top 20</h2>
<table>
  <thead><tr><th>VM 名</th><th>Guest OS</th><th>CPU / RAM</th><th>カテゴリ</th><th>概算工数</th><th>主な検出</th></tr></thead>
  <tbody>{detail_rows or '<tr><td colspan="6">該当なし</td></tr>'}</tbody>
</table>

<p class="meta">
⚠️ 本レポートは <strong>VMX/OVF メタデータの静的解析による事前見積もり</strong> です。
実行時の I/O 負荷・vSphere クラスタ依存・カスタムタグ等は別途検証してください。
最終工数は人手レビュー + 移行リハーサルを実施してください。<br>
生成: {datetime.now().isoformat(timespec='seconds')} / VMware2KVM diagnose.py
</p>
</body></html>"""
    out_path.write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="VMware の .vmx / .ovf を走査して KVM/Nutanix 移行可能性を診断",
    )
    parser.add_argument("input_dir", help="走査対象のディレクトリ")
    parser.add_argument("-o", "--output", default="report.csv",
                        help="CSV 出力先")
    parser.add_argument("--html", default=None, help="HTML サマリ出力先（任意）")
    args = parser.parse_args(argv)

    root = Path(args.input_dir).resolve()
    if not root.is_dir():
        print(f"エラー: ディレクトリではありません: {root}", file=sys.stderr)
        return 2

    files = collect_files(root)
    if not files:
        print(f"対象ファイル (.vmx/.ovf) が見つかりません: {root}", file=sys.stderr)
        return 1

    print(f"走査中: {len(files)} VM...", file=sys.stderr)
    diags = [diagnose_file(p, root) for p in files]

    out_csv = Path(args.output).resolve()
    write_csv(diags, out_csv)
    print(f"[OK] CSV: {out_csv}", file=sys.stderr)

    if args.html:
        out_html = Path(args.html).resolve()
        write_html(diags, out_html)
        print(f"[OK] HTML: {out_html}", file=sys.stderr)

    agg = aggregate(diags)
    by = agg["by_category"]
    print("\n=== 集計 ===", file=sys.stderr)
    print(f"  AUTO   : {by.get('AUTO', 0)} VM", file=sys.stderr)
    print(f"  REVIEW : {by.get('REVIEW', 0)} VM", file=sys.stderr)
    print(f"  MANUAL : {by.get('MANUAL', 0)} VM", file=sys.stderr)
    print(f"  合計リソース: {agg['total_vcpus']} vCPU / {agg['total_memory_gb']:.1f} GB / {agg['total_disks']} ディスク", file=sys.stderr)
    print(f"  概算工数: {agg['total_effort_hr']} 時間 (≒ {agg['total_effort_pd']} 人日)", file=sys.stderr)
    print("\n  移行阻害 Top 5:", file=sys.stderr)
    for name, count in agg["top_unsupported"][:5]:
        print(f"    - {name}: {count}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
