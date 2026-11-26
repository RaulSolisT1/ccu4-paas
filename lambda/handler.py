import json
import hashlib


def lambda_handler(event, context):
    for rec in event["Records"]:
        body = json.loads(rec["body"])
        digest = hashlib.sha256(json.dumps(body).encode()).hexdigest()
        print(f"[JOB] id={body.get('id')} digest={digest}")
    return {"processed": len(event["Records"])}
