#!/usr/bin/env python3
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    tree = ET.parse(args.source)
    root = tree.getroot()
    root.find("name").text = "__DOMAIN_NAME__"
    root.find("uuid").text = "__DOMAIN_UUID__"
    description = root.find("description")
    if description is not None:
        description.text = "Disposable Windows Coding Benchmark domain"

    nvram = root.find("./os/nvram")
    if nvram is None:
        raise RuntimeError("source domain has no NVRAM")
    nvram.text = "__NVRAM_PATH__"

    devices = root.find("devices")
    if devices is None:
        raise RuntimeError("source domain has no devices")
    system_disks = [disk for disk in devices.findall("disk") if disk.get("device") == "disk"]
    if len(system_disks) != 1:
        raise RuntimeError(f"expected one system disk, found {len(system_disks)}")
    disk_source = system_disks[0].find("source")
    disk_source.set("file", "__OVERLAY_PATH__")
    boot = system_disks[0].find("boot")
    if boot is None:
        boot = ET.SubElement(system_disks[0], "boot")
    boot.set("order", "1")

    removable_tags = {"graphics", "sound", "audio", "video", "redirdev"}
    for child in list(devices):
        if child.tag == "disk" and child.get("device") == "cdrom":
            devices.remove(child)
        elif child.tag in removable_tags:
            devices.remove(child)
        elif child.tag == "channel" and child.find("target") is not None and child.find("target").get("name", "").startswith("com.redhat.spice"):
            devices.remove(child)
        elif child.tag == "input" and child.get("bus") == "usb":
            devices.remove(child)

    interface = devices.find("interface")
    if interface is None:
        raise RuntimeError("source domain has no network interface")
    interface.find("mac").set("address", "__MAC_ADDRESS__")
    interface.find("source").set("network", "wcb-nat")

    tpm = devices.find("tpm/backend")
    if tpm is None:
        raise RuntimeError("source domain has no TPM backend")

    ET.indent(tree, space="  ")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(args.destination, encoding="unicode", xml_declaration=False)
    with args.destination.open("a", encoding="utf-8") as handle:
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

