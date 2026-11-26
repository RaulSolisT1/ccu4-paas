import io
import json
import time
import zipfile

import boto3

s = boto3.Session(profile_name="admin", region_name="us-west-2")
iam, sqs, lam = s.client("iam"), s.client("sqs"), s.client("lambda")

role = iam.create_role(
    RoleName="ccu4-lambda-role",
    AssumeRolePolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow",
                       "Principal": {"Service": "lambda.amazonaws.com"},
                       "Action": "sts:AssumeRole"}]}))["Role"]["Arn"]
iam.attach_role_policy(
    RoleName="ccu4-lambda-role",
    PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole")

url = sqs.create_queue(QueueName="ccu4-jobs")["QueueUrl"]
arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])[
    "Attributes"]["QueueArn"]

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.write("../lambda/handler.py", "handler.py")

time.sleep(10)  # propagacion del rol IAM
lam.create_function(FunctionName="ccu4-job", Runtime="python3.12", Role=role,
                    Handler="handler.lambda_handler",
                    Code={"ZipFile": buf.getvalue()}, Timeout=30)
time.sleep(5)
lam.create_event_source_mapping(EventSourceArn=arn, FunctionName="ccu4-job",
                                BatchSize=5)
print("SQS_QUEUE_URL=" + url)
