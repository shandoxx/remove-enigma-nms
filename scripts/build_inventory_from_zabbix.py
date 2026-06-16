#!/usr/bin/env python3

import sys
from pathlib import Path

import requests
import yaml

ZABBIX_URL = "http://10.10.10.111/zabbix/api_jsonrpc.php"
OUT_FILE = Path("inventory/zabbix/cisco_access_switches.yml")

EXCLUDE_WORDS = [
    "router",
    "bgp",
    "core",
    "isr",
    "hub",
]

INCLUDE_HINTS = [
    "fsw",
    "2960",
    "9200",
    "switch",
]

def zbx(method, params, auth=None):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }

    if auth:
        payload["auth"] = auth

    r = requests.post(
        ZABBIX_URL,
        json=payload,
        timeout=30,
    )

    r.raise_for_status()

    data = r.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    return data["result"]

def wanted(hostname, templates, groups):
    text = f"{hostname} {templates} {groups}".lower()

    if "cisco" not in text:
        return False

    if any(x in text for x in EXCLUDE_WORDS):
        return False

    if any(x in text for x in INCLUDE_HINTS):
        return True

    return False

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <user> <password>")
        sys.exit(1)

    user = sys.argv[1]
    password = sys.argv[2]

    auth = zbx(
        "user.login",
        {
            "username": user,
            "password": password,
        }
    )

    hosts = zbx(
        "host.get",
        {
            "output": ["host", "name"],
            "selectInterfaces": ["ip", "main"],
            "selectParentTemplates": ["name"],
            "selectGroups": ["name"],
            "filter": {"status": 0},
        },
        auth,
    )

    inventory = {
        "all": {
            "children": {
                "cisco_access_switches": {
                    "vars": {
                        "ansible_connection": "ansible.netcommon.network_cli",
                        "ansible_network_os": "cisco.ios.ios",
                        "ansible_network_cli_ssh_type": "paramiko",
                        "ansible_user": "{{ vault_ansible_user }}",
                        "ansible_password": "{{ vault_ansible_password }}",
                        "ansible_become": True,
                        "ansible_become_method": "enable",
                        "ansible_become_password": "{{ vault_ansible_become_password }}",
                        "ansible_paramiko_look_for_keys": False,
                        "ansible_paramiko_allow_agent": False,
                        "ansible_ssh_common_args": (
                            "-oKexAlgorithms=+diffie-hellman-group1-sha1,"
                            "diffie-hellman-group14-sha1,"
                            "diffie-hellman-group-exchange-sha1 "
                            "-oHostKeyAlgorithms=+ssh-rsa "
                            "-oPubkeyAcceptedAlgorithms=+ssh-rsa "
                            "-oPubkeyAuthentication=no "
                            "-oPreferredAuthentications=password "
                            "-oPasswordAuthentication=yes "
                            "-oStrictHostKeyChecking=no"
                        ),
                    },
                    "hosts": {},
                }
            }
        }
    }

    count = 0

    for h in hosts:
        hostname = h["host"]

        templates = " ".join(
            t["name"]
            for t in h.get("parentTemplates", [])
        )

        groups = " ".join(
            g["name"]
            for g in h.get("groups", [])
        )

        if not wanted(hostname, templates, groups):
            continue

        interfaces = h.get("interfaces") or []

        main_if = next(
            (
                i for i in interfaces
                if str(i.get("main")) == "1"
            ),
            interfaces[0] if interfaces else None,
        )

        if not main_if:
            continue

        ip = main_if.get("ip")

        if not ip:
            continue

        inventory["all"]["children"]["cisco_access_switches"]["hosts"][hostname] = {
            "ansible_host": ip
        }

        count += 1

        print(f"[MATCH] {hostname} -> {ip}")

    OUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUT_FILE.write_text(
        yaml.safe_dump(
            inventory,
            sort_keys=False,
        )
    )

    print()
    print(f"Generated inventory: {OUT_FILE}")
    print(f"Matched access switches: {count}")

if __name__ == "__main__":
    main()
