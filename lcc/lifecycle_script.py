#!/usr/bin/env python

import argparse
from enum import Enum
import json
import os
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

class ExecuteBashScript:
    def __init__(self, script_name: str):
        self.script_name = script_name

    def run(self, *args):
        print(f"Execute script: {self.script_name} {' '.join([str(x) for x in args])}")
        result = subprocess.run(["sudo", "bash", self.script_name, *args])
        result.check_returncode()
        print(f"Script {self.script_name} executed successully")

class ResourceConfig:
    INSTANCE_GROUP_NAME = "Name"
    INSTANCE_NAME = "InstanceName"
    CUSTOMER_IP_ADDRESS = "CustomerIpAddress"

    def __init__(self, path: str):
        with open(path, "r") as f:
            self._config = json.load(f)

    def find_instance_by_address(self, address) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        for group in self._config["InstanceGroups"]:
            for instance in group["Instances"]:
                if instance.get(ResourceConfig.CUSTOMER_IP_ADDRESS) == address:
                    return group, instance
        return None, None

    def get_list_of_addresses(self, group_name) -> List[str]:
        for group in self._config["InstanceGroups"]:
            if group.get(ResourceConfig.INSTANCE_GROUP_NAME) != group_name:
                continue
            return [i.get(ResourceConfig.CUSTOMER_IP_ADDRESS) for i in group["Instances"]]
        return []

def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def main(args):
    resource_config = ResourceConfig(args.resource_config)

    self_ip = get_ip_address()
    print(f"This node ip address is {self_ip}")

    group, instance = resource_config.find_instance_by_address(self_ip)
    if instance is None:
        raise ValueError("This instance not found in resource config. Can't process")
    print(group)

    ExecuteBashScript("./utils/install_package.sh").run()

    ExecuteBashScript("./apply_hotfix.sh").run()

    ExecuteBashScript("./utils/install_docker.sh").run()

    subprocess.run(["sudo", "-u", "ubuntu", "python3.9", "-u", "./configure_k8s.py"], check=True)

    print("[INFO]: Success: All provisioning scripts completed")

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("-rc", "--resource_config", help="Resource config JSON file containing Ip_address of head, login and compute nodes")
    args=parser.parse_args()

    main(args)
