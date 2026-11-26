import os
import boto3

ec2 = boto3.client("ec2", region_name=os.getenv("AWS_REGION", "us-west-2"))
r = ec2.describe_instances(Filters=[
    {"Name": "tag:Project", "Values": ["ccu4"]},
    {"Name": "instance-state-name", "Values": ["pending", "running", "stopped"]}])
ids = [i["InstanceId"] for x in r["Reservations"] for i in x["Instances"]]
if ids:
    ec2.terminate_instances(InstanceIds=ids)
    print("Terminadas:", ids)
else:
    print("Nada vivo")
