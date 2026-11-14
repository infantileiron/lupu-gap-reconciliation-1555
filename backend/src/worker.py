import logging,time
from pathlib import Path
import redis
from src.config.settings import REDIS_URL
from src.services.run import execute
from src.services.conservation import run_conservation
from src.utils.repository import init_db
logging.basicConfig(level=logging.INFO)
def main():
    init_db(); client=redis.Redis.from_url(REDIS_URL)
    while True:
        Path("/tmp/worker-heartbeat").write_text(str(time.time()))
        try:
            item=client.blpop(["gap-reconstruction:jobs","gap-conservation:jobs"], timeout=3)
            if item:
                queue,job=item[0].decode(),item[1].decode()
                if queue=="gap-conservation:jobs": run_conservation(job)
                else: execute(job)
        except Exception:
            logging.exception("worker failure");time.sleep(2)
if __name__=="__main__": main()
