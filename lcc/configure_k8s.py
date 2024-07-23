import os
import time
import subprocess
import tempfile
import re
import json
import ipaddress
import getpass
import socket
import fcntl
import struct
import io


# --------------
# Configurations

# If this script is executed by root already, this variable can be empty
if getpass.getuser() == "root":
    sudo_command = []
else:
    sudo_command = ["sudo","-E"]

# Prefix of SecretsManager secret name
secret_name = "hyperpod-k8s-"

# Configuration for retries and timeout
join_info_timeout = 5 * 60 # 5min
nodes_ready_timeout = 5 * 60 # 5min
kubectl_apply_max_retries = 10


# ---

class ResourceConfig:

    _instance = None

    @staticmethod
    def instance():
        if ResourceConfig._instance is None:
            ResourceConfig._instance = ResourceConfig()
        return ResourceConfig._instance

    def __init__(self):

        if "SAGEMAKER_RESOURCE_CONFIG_PATH" in os.environ:
            resource_config_filename = os.environ["SAGEMAKER_RESOURCE_CONFIG_PATH"]
        else:
            resource_config_filename = "/opt/ml/config/resource_config.json"

        # due to directory permission, regular user cannot open the file.
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_filename = os.path.join(tmp_dir, os.path.basename(resource_config_filename))

            run_subprocess_wrap( [ *sudo_command, "cp", resource_config_filename, tmp_filename ] )
            run_subprocess_wrap( [ *sudo_command, "chmod", "644", tmp_filename ] )

            with open(tmp_filename) as fd:
                d = fd.read()

        self.d = json.loads(d)

        # sample contents of resource_config.json
        """
        {
            'ClusterConfig': {
                'ClusterArn': 'arn:aws:sagemaker:us-west-2:842413447717:cluster/kb8v11zrrpvr',
                'ClusterName': 'K8-1'
            },
            'InstanceGroups': [
                {
                    'InstanceType': 'ml.t3.xlarge',
                    'Instances': [
                        {
                            'AgentIpAddress': '172.16.102.203',
                            'CustomerIpAddress': '10.1.113.28',
                            'InstanceId': 'i-07259dd159a1c7130',
                            'InstanceName': 'ControllerGroup-1'
                        }
                    ],
                    'Name': 'ControllerGroup'
                },
                {
                    'InstanceType': 'ml.t3.xlarge',
                    'Instances': [
                        {
                            'AgentIpAddress': '172.16.100.157',
                            'CustomerIpAddress': '10.1.38.128',
                            'InstanceId': 'i-0cbbe3075137ffa1d',
                            'InstanceName': 'WorkerGroup-1'
                        },
                        {
                            'AgentIpAddress': '172.16.98.182',
                            'CustomerIpAddress': '10.1.29.16',
                            'InstanceId': 'i-0cc2532921ec06344',
                            'InstanceName': 'WorkerGroup-2'
                        }
                    ],
                    'Name': 'WorkerGroup'
                }
            ]
        }
        """

    def get_cluster_name(self):
        return self.d["ClusterConfig"]["ClusterName"]

    def get_cluster_arn(self):
        return self.d["ClusterConfig"]["ClusterArn"]

    def get_region(self):
        arn = self.get_cluster_arn()
        re_result = re.match( "arn:aws:sagemaker:([a-z0-9-]+):([0-9]+):cluster/([a-z0-9]+)", arn )
        assert re_result, "Region name not found in cluster ARN"
        return re_result.group(1)

    def get_cluster_id(self):
        arn = self.get_cluster_arn()
        re_result = re.match( "arn:aws:sagemaker:([a-z0-9-]+):([0-9]+):cluster/([a-z0-9]+)", arn )
        assert re_result, "Cluster ID not found in cluster ARN"
        return re_result.group(3)

    def iter_instances(self):
        for instance_group in self.d["InstanceGroups"]:
            for instance in instance_group["Instances"]:
                instance2 = instance.copy()
                instance2["InstanceType"] = instance_group["InstanceType"]
                instance2["InstanceGroupName"] = instance_group["Name"]
                instance2["Name"] = "ip-" + instance["CustomerIpAddress"].replace(".","-")
                yield instance2


class IpAddressInfo:

    _instance = None

    @staticmethod
    def instance():
        if IpAddressInfo._instance is None:
            IpAddressInfo._instance = IpAddressInfo()
        return IpAddressInfo._instance

    def __init__(self):

        interface_name = b"ens6"

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr = socket.inet_ntoa(fcntl.ioctl(sock, 35095, struct.pack('256s', interface_name))[20:24])
        self.mask = socket.inet_ntoa(fcntl.ioctl(sock, 35099, struct.pack('256s', interface_name))[20:24])
        self.cidr = str(ipaddress.IPv4Network(self.addr+"/"+self.mask, strict=False))


def run_subprocess_wrap(cmd):

    captured_stdout = io.StringIO()

    p = subprocess.Popen( cmd, bufsize=1, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT )
    for line in iter(p.stdout.readline, ""):
        captured_stdout.write(line)
        print( line, end="", flush=True )
    p.wait()

    if p.returncode != 0:
        raise ChildProcessError(f"Subprocess {cmd} returned non-zero exit code {p.returncode}.")

    return captured_stdout.getvalue()


def install_python_packages():

    print("---")
    print("Installing Python packages")
    run_subprocess_wrap( [ "pip3", "install", "boto3" ] )


def configure_bridged_traffic():

    print("---")
    print("Configuring bridged traffic")
    run_subprocess_wrap( [ "bash", "./utils/configure_bridged_traffic.sh" ] )


def configure_cri_containerd():

    print("---")
    print("Configuring containerd config file")

    dst_filename = "/etc/containerd/config.toml"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_filename = os.path.join(tmp_dir, os.path.basename(dst_filename))

        with open("./utils/containerd_config.template") as fd_template:
            d = fd_template.read()

        containerd_root = "/var/lib/containerd"

        # If GPUs are available, use "nvidia" runtime
        result = subprocess.run(["nvidia-smi"])
        if result.returncode==0:
            default_runtime_name = "nvidia"
        else:
            default_runtime_name = "runc"

        d = d.format(root=containerd_root, default_runtime_name=default_runtime_name)
        print(d)

        with open(tmp_filename,"w") as fd:
            fd.write(d)

        run_subprocess_wrap( [ *sudo_command, "chmod", "644", tmp_filename ] )
        run_subprocess_wrap( [ *sudo_command, "chown", "root:root", tmp_filename ] )
        run_subprocess_wrap( [ *sudo_command, "cp", tmp_filename, dst_filename ] )

    print("---")
    print("Configuring containerd.service")

    dst_filename = "/usr/lib/systemd/system/containerd.service"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_filename = os.path.join(tmp_dir, os.path.basename(dst_filename))

        with open(dst_filename) as fd_src:
            d = fd_src.read()

        # Equivalent to "ulimit -l unlimited"
        d = re.sub( r"\[Service\]", "[Service]\nLimitMEMLOCK=infinity", d )
        print(d)

        with open(tmp_filename,"w") as fd:
            fd.write(d)

        run_subprocess_wrap( [ *sudo_command, "chmod", "644", tmp_filename ] )
        run_subprocess_wrap( [ *sudo_command, "chown", "root:root", tmp_filename ] )
        run_subprocess_wrap( [ *sudo_command, "cp", tmp_filename, dst_filename ] )

    print("---")
    print("Restarting containerd")

    run_subprocess_wrap( [ *sudo_command, "systemctl", "daemon-reload" ] )
    run_subprocess_wrap( [ *sudo_command, "systemctl", "restart", "containerd" ] )


def install_kubernetes():

    print("---")
    print("Installing Kubernetes")

    run_subprocess_wrap([ "bash", "./utils/install_kubernetes.sh" ])

    run_subprocess_wrap( [ *sudo_command, "systemctl", "enable", "kubelet" ] )
    run_subprocess_wrap( [ *sudo_command, "systemctl", "start", "kubelet" ] )


def get_secret_name():
    cluster_name = ResourceConfig.instance().get_cluster_name()
    return f"{secret_name}-{cluster_name}"

def get_join_info_from_secret():

    import boto3

    region_name = ResourceConfig.instance().get_region()

    session = boto3.session.Session()
    secretsmanager_client = session.client(
        service_name="secretsmanager",
        region_name=region_name
    )

    secret_name = get_secret_name()

    print(f"Fetching joining token from {secret_name}")

    try:
        response = secretsmanager_client.get_secret_value(
            SecretId=secret_name
        )
    except secretsmanager_client.exceptions.ResourceNotFoundException:
        return None

    return json.loads(response["SecretString"])


def init_worker_node():

    # https://kubernetes.io/docs/reference/setup-tools/kubeadm/kubeadm-join/

    print("---")
    print("Getting join token from master node.")

    t0 = time.time()
    while True:
        join_info = get_join_info_from_secret()
        if join_info is not None:
            break
        if time.time() - t0 >= join_info_timeout:
            raise TimeoutError("Getting join token timed out.")
        print("Join information is not ready in SecretsManager. Retrying...")
        time.sleep(10)

    print("---")
    print("Joining to the cluster")
    run_subprocess_wrap([ *sudo_command, "kubeadm", "join", join_info["master_addr_port"], "--token", join_info["token"], "--discovery-token-ca-cert-hash", "sha256:"+join_info["discovery_token_ca_cert_hash"] ])

def add_labels_to_nodes():

    print("---")
    print(f"Adding label (node.kubernetes.io/instance-type) to nodes")
    cluster_name = ResourceConfig.instance().get_cluster_name()

    for instance in ResourceConfig.instance().iter_instances():
        name = instance["Name"]
        instance_type = instance["InstanceType"]

        run_subprocess_wrap( [ "kubectl", "label", "node", name, f"node.kubernetes.io/instance-type={instance_type}" ] )
        run_subprocess_wrap( [ "kubectl", "label", "node", name, f"sagemaker.aws.dev/cluster={cluster_name}" ] )
        run_subprocess_wrap( [ "kubectl", "label", "node", name, f"sagemaker.aws.dev/launch-type=HyperPod" ] )

def configure_k8s():

    print("Starting Kubernetes configuration steps")

    install_python_packages()
    configure_bridged_traffic()
    configure_cri_containerd()
    install_kubernetes()

    init_worker_node()

    print("---")
    print("Finished Kubernetes configuration steps")


if __name__ == "__main__":

    configure_k8s()
