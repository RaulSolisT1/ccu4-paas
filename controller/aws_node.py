import os
import time
import subprocess

import boto3
import requests
from botocore.exceptions import ClientError

REGION = os.getenv("AWS_REGION", "us-west-2")
IMAGE = os.getenv("IMAGE", "ghcr.io/raulsolist1/api:latest")
NODE_PORT = int(os.getenv("NODE_PORT", "80"))
KEY_NAME = os.getenv("KEY_NAME")   # opcional: par de llaves para el tunel a Redis
KEY_PATH = os.getenv("KEY_PATH")   # ruta al .pem
SG_NAME = "ccu4-sg"
ec2 = boto3.client("ec2", region_name=REGION)


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def my_ip():
    return requests.get("https://checkip.amazonaws.com", timeout=5).text.strip()


def ensure_sg():
    r = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": [SG_NAME]}])
    if r["SecurityGroups"]:
        sg = r["SecurityGroups"][0]["GroupId"]
    else:
        vpc = ec2.describe_vpcs(
            Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
        sg = ec2.create_security_group(GroupName=SG_NAME, Description="ccu4",
                                       VpcId=vpc)["GroupId"]
        log(f"SG creado {sg}")
    cidr = f"{my_ip()}/32"
    for port in (22, NODE_PORT):
        try:
            ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[
                {"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
                 "IpRanges": [{"CidrIp": cidr}]}])
            log(f"regla agregada {cidr}:{port}")
        except ClientError as e:
            if "Duplicate" not in str(e):
                raise
    return sg


def ubuntu_ami():
    imgs = ec2.describe_images(Owners=["099720109477"], Filters=[
        {"Name": "name",
         "Values": ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]},
        {"Name": "state", "Values": ["available"]}])["Images"]
    return sorted(imgs, key=lambda i: i["CreationDate"])[-1]["ImageId"]


USER_DATA = f"""#!/bin/bash
apt-get update -y
apt-get install -y docker.io
systemctl enable --now docker
docker run -d --restart always --network host -e NODE=aws -e REDIS_URL=redis://127.0.0.1:6379/0 {IMAGE} uvicorn main:app --host 0.0.0.0 --port {NODE_PORT}
sleep 15
docker ps -a
docker logs $(docker ps -aq | head -1) 2>&1 | tail -20
ss -ltn | grep {NODE_PORT}
curl -s -m 5 localhost:{NODE_PORT}/health
"""


def wait_healthy(ip, timeout=300):
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        try:
            if requests.get(f"http://{ip}:{NODE_PORT}/health", timeout=3).ok:
                return True
        except Exception as e:
            last = str(e)[:150]
        time.sleep(5)
    log(f"ultimo error de /health desde tu PC: {last}")
    return False


def terminate(node):
    if node.get("tunnel"):
        node["tunnel"].terminate()
    ec2.terminate_instances(InstanceIds=[node["id"]])
    log(f"[ENVIADO] TerminateInstances {node['id']}")
    ec2.get_waiter("instance_terminated").wait(InstanceIds=[node["id"]])
    log(f"[RECIBIDO] instancia terminada {node['id']}")


def spawn():
    params = dict(ImageId=ubuntu_ami(), InstanceType="t3.micro",
                  MinCount=1, MaxCount=1, SecurityGroupIds=[ensure_sg()],
                  UserData=USER_DATA,
                  TagSpecifications=[{"ResourceType": "instance",
                                      "Tags": [{"Key": "Project", "Value": "ccu4"}]}])
    if KEY_NAME:
        params["KeyName"] = KEY_NAME
    log("[ENVIADO] RunInstances t3.micro")
    iid = ec2.run_instances(**params)["Instances"][0]["InstanceId"]
    log(f"[RECIBIDO] instancia creada {iid}")
    ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
    ip = ec2.describe_instances(InstanceIds=[iid])[
        "Reservations"][0]["Instances"][0]["PublicIpAddress"]
    log(f"[RECIBIDO] running {iid} ip={ip}")
    if not wait_healthy(ip):
        try:
            out = ec2.get_console_output(InstanceId=iid, Latest=True).get("Output", "")
            log("CONSOLE OUTPUT (ultimas lineas):\n" + "\n".join(out.splitlines()[-60:]))
        except Exception as e:
            log(f"no se pudo leer la consola: {e}")
        terminate({"id": iid, "ip": ip, "tunnel": None})
        raise RuntimeError("el nodo AWS nunca respondio /health")
    tunnel = None
    if KEY_PATH:
        tunnel = subprocess.Popen([
            "ssh", "-i", KEY_PATH, "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=15", "-N",
            "-R", "6379:127.0.0.1:6379", f"ubuntu@{ip}"])
        log("tunel inverso a Redis local abierto")
    log(f"nodo sano {iid} ip={ip} puerto={NODE_PORT}")
    return {"id": iid, "ip": ip, "tunnel": tunnel}


if __name__ == "__main__":  # prueba manual del Milestone 2
    n = spawn()
    time.sleep(20)
    terminate(n)
