# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- README に「これは何？（30秒で）」「想定ユースケース・価格帯」セクションを追加
- SECURITY.md を追加（脆弱性報告フロー）
- 商用利用・カスタマイズ依頼の連絡先を README 末尾に明記
- **scripts/diagnose.py** — VMware → KVM/Nutanix 移行 事前診断スクリプト
  - .vmx / .ovf を走査し各 VM を AUTO / REVIEW / MANUAL 分類
  - 移行阻害ランキング Top 10（vSAN / FT / SR-IOV / vGPU / PCI Passthrough 等）
  - 合計 vCPU / メモリ / ディスク数を集計
  - 概算工数（時間／人日）
  - HTML サマリ出力（4 KPI ボックス、A4 1〜2 枚）
  - virt-v2v との住み分けを scripts/README.md に明記

## [0.1.0]

### Added
- 初版リリース
