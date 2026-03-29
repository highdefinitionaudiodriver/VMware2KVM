#!/bin/bash
echo "=== VMware2KVM Build ==="
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --windowed --name VMware2KVM main.py
echo "=== Build Complete ==="
echo "Output: dist/VMware2KVM"
