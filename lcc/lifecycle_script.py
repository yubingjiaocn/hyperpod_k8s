#!/usr/bin/env python

import argparse
from enum import Enum
import json
import os
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

SLURM_CONF = os.getenv("SLURM_CONF", "/opt/slurm/etc/slurm.conf")

class SlurmNodeType(str, Enum):
    HEAD_NODE = "controller"
    LOGIN_NODE = "login"
    COMPUTE_NODE = "compute"


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


class ProvisioningParameters:
    WORKLOAD_MANAGER_KEY: str = "workload_manager"

    def __init__(self, path: str):
        with open(path, "r") as f:
            self._params = json.load(f)

    @property
    def workload_manager(self) -> Optional[str]:
        return self._params.get(ProvisioningParameters.WORKLOAD_MANAGER_KEY)

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


def wait_for_slurm_conf(controllers: List[str]) -> bool:
    """
    SageMaker agents do a slurm configuration. Wait for a signal that slurm is ready to start.
    This means that we can start controller, or do additional setup
    Returns:
        bool: True if valid slurm configuration found
    """
    sleep = 5 # sec
    timeout = 60  # sec
    for i in range(timeout // sleep):
        if not os.path.exists(SLURM_CONF):
            print("slurm.conf is not present. It is fine for login/compute nodes")
            return True
        with open(SLURM_CONF, "rt") as f:
            data = f.read()
            # check if controller information is present
            for ip in controllers:
                if ip in data:
                    print("slurm.conf found. It contains at least one controller address")
                    return True
        time.sleep(sleep)
    return False

def wait_for_scontrol():
    """
    Checks if 'scontrol show nodes' command returns output within specified time.
    This means we can proceed with install scripts which require nodes to be registered with slurm.
    Returns:
        bool: True if the command returns output from scontrol within the specified time, False otherwise.
    """
    timeout = 120
    sleep = 5
    for i in range (timeout // sleep):
        try:
            output = subprocess.check_output(['scontrol', 'show', 'nodes'])
            if output.strip():
                print("Nodes registered with Slurm, Proceeding with install scripts.", output)
                return True
        except subprocess.CalledProcessError:
            pass

        print(f"Waiting for output. Retrying in {sleep} seconds...")
        time.sleep(sleep)

    print(f"Exceeded maximum wait time of {timeout} seconds. No output from scontrol.")
    return False


def main(args):
    resource_config = ResourceConfig(args.resource_config)

    self_ip = get_ip_address()
    print(f"This node ip address is {self_ip}")

    group, instance = resource_config.find_instance_by_address(self_ip)
    if instance is None:
        raise ValueError("This instance not found in resource config. Can't process")
    print(group)

    node_type = SlurmNodeType.COMPUTE_NODE

    ExecuteBashScript("./apply_hotfix.sh").run(node_type)

    ExecuteBashScript("./utils/install_docker.sh").run()

    subprocess.run(["sudo", "-u", "ubuntu", "python3.9", "-u", "./configure_k8s.py"], check=True)

    print("[INFO]: Success: All provisioning scripts completed")


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("-rc", "--resource_config", help="Resource config JSON file containing Ip_address of head, login and compute nodes")
    parser.add_argument("-pp", "--provisioning_parameters", help="Provisioning Parameters containing the head, login and compute ID/names")
    args=parser.parse_args()

    main(args)
