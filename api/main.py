import os
import json
import time
import uuid
import hashlib

import psutil
import redis
import boto3
from fastapi import FastAPI, Request, Response
from prometheus_client import (Counter, Histogram, Gauge,
                               generate_latest, CONTENT_TYPE_LATEST)

NODE = os.getenv("NODE", "local")
app = FastAPI()
r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"),
                         socket_connect_timeout=0.5, socket_timeout=0.5)

REQS = Counter("http_requests_total", "Total requests", ["node"])
LAT = Histogram("http_request_seconds", "Latency")
INFLIGHT = Gauge("http_inflight", "In-flight requests")
CPU = Gauge("node_cpu_percent", "CPU percent")
CPU.set_function(lambda: psutil.cpu_percent(interval=None))


@app.middleware("http")
async def count(request: Request, call_next):
    if request.url.path in ("/metrics", "/health"):
        return await call_next(request)
    INFLIGHT.inc()
    start = time.time()
    try:
        return await call_next(request)
    finally:
        INFLIGHT.dec()
        LAT.observe(time.time() - start)
        REQS.labels(NODE).inc()


@app.get("/health")
def health():
    return {"status": "ok", "node": NODE}


@app.get("/work")
def work(n: int = 20000):
    h = b"x"
    for _ in range(n):
        h = hashlib.sha256(h).digest()
    hits = None
    try:
        hits = r.incr("hits")  # el estado vive en Redis, no en la API
    except Exception:
        pass
    return {"node": NODE, "hits": hits}


@app.post("/job")
def job():
    url = os.getenv("SQS_QUEUE_URL")
    if not url:
        return {"queued": False}
    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-west-2"))
    jid = str(uuid.uuid4())
    sqs.send_message(QueueUrl=url,
                     MessageBody=json.dumps({"id": jid, "ts": time.time()}))
    return {"queued": True, "id": jid}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
