#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

# from beartype import BeartypeConf
# from beartype.claw import beartype_all  # <-- you didn't sign up for this
# beartype_all(conf=BeartypeConf(violation_type=UserWarning))    # <-- emit warnings from all code

from api.utils.log_utils import initRootLogger
from plugin import GlobalPluginManager
initRootLogger("ragflow_server")

import logging
import os
import signal
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

from werkzeug.serving import run_simple
from api import settings
from api.apps import app
from api.db.runtime_config import RuntimeConfig
from api.db.services.document_service import DocumentService
from api import utils

from api.db.db_models import init_database_tables as init_web_db
from api.db.init_data import init_web_data
from api.versions import get_ragflow_version
from api.utils import show_configs
from rag.settings import print_rag_settings
from rag.utils.redis_conn import RedisDistributedLock

# 导入Nacos服务注册功能
try:
    from api.utils.nacos_client import register_ragflow_service, get_nacos_client
    NACOS_ENABLED = True
except ImportError:
    NACOS_ENABLED = False
    logging.warning("Nacos client not available, service discovery disabled")

logging.info(f"Nacos enabled: {NACOS_ENABLED}")
stop_event = threading.Event()

RAGFLOW_DEBUGPY_LISTEN = int(os.environ.get('RAGFLOW_DEBUGPY_LISTEN', "0"))

def update_progress():
    lock_value = str(uuid.uuid4())
    redis_lock = RedisDistributedLock("task/progress/lock", lock_value=lock_value, timeout=60)
    logging.info(f"update_progress lock_value: {lock_value}")
    while not stop_event.is_set():
        try:
            if redis_lock.acquire():
                DocumentService.update_progress()
                redis_lock.release()
            stop_event.wait(6)
        except Exception:
            logging.exception("update_progress exception")
        finally:
            redis_lock.release()

def signal_handler(sig, frame):
    logging.info("Received interrupt signal, shutting down...")
    
    # 注销Nacos服务
    if NACOS_ENABLED:
        try:
            nacos_client = get_nacos_client()
            if nacos_client:
                registration_ip = os.getenv('NACOS_REGISTRATION_IP', settings.HOST_IP)
                nacos_client.deregister_ragflow_service("ragflow", registration_ip, settings.HOST_PORT)
                logging.info("Deregistered RAGFlow service from Nacos")
        except Exception as e:
            logging.error(f"Error deregistering service from Nacos: {e}")
    
    
    stop_event.set()
    time.sleep(1)
    sys.exit(0)

if __name__ == '__main__':
    logging.info(r"""
        ____   ___    ______ ______ __               
       / __ \ /   |  / ____// ____// /____  _      __
      / /_/ // /| | / / __ / /_   / // __ \| | /| / /
     / _, _// ___ |/ /_/ // __/  / // /_/ /| |/ |/ / 
    /_/ |_|/_/  |_|\____//_/    /_/ \____/ |__/|__/                             

    """)
    logging.info(
        f'RAGFlow version: {get_ragflow_version()}'
    )
    logging.info(
        f'project base: {utils.file_utils.get_project_base_directory()}'
    )
    show_configs()
    settings.init_settings()
    print_rag_settings()

    if RAGFLOW_DEBUGPY_LISTEN > 0:
        logging.info(f"debugpy listen on {RAGFLOW_DEBUGPY_LISTEN}")
        import debugpy
        debugpy.listen(("0.0.0.0", RAGFLOW_DEBUGPY_LISTEN))

    # init db
    init_web_db()
    init_web_data()
    # init runtime config
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version", default=False, help="RAGFlow version", action="store_true"
    )
    parser.add_argument(
        "--debug", default=False, help="debug mode", action="store_true"
    )
    args = parser.parse_args()
    if args.version:
        print(get_ragflow_version())
        sys.exit(0)

    RuntimeConfig.DEBUG = args.debug
    if RuntimeConfig.DEBUG:
        logging.debug("run on debug mode")

    RuntimeConfig.init_env()
    RuntimeConfig.init_config(JOB_SERVER_HOST=settings.HOST_IP, HTTP_PORT=settings.HOST_PORT)

    GlobalPluginManager.load_plugins()

    # 注册服务到Nacos
    if NACOS_ENABLED and os.getenv('NACOS_ENABLED', 'false').lower() == 'true':
        try:
            metadata = {
                'version': get_ragflow_version(),
                'environment': os.getenv('ENVIRONMENT', 'production'),
                'service_type': 'ragflow',
                'debug': RuntimeConfig.DEBUG
            }
            
            registration_ip = os.getenv('NACOS_REGISTRATION_IP', '')
            logging.info(f"Registering to Nacos with IP: {registration_ip}")
            
            success = register_ragflow_service(
                host=registration_ip,
                port=settings.HOST_PORT,
                metadata=metadata
            )
            
            if success:
                logging.info("Successfully registered RAGFlow service to Nacos")
                # 启动心跳线程
                nacos_client = get_nacos_client()
                if nacos_client:
                    registration_ip = os.getenv('NACOS_REGISTRATION_IP', '')
                    nacos_client.start_heartbeat_thread("ragflow", registration_ip, settings.HOST_PORT)
            else:
                logging.warning("Failed to register RAGFlow service to Nacos")
        except Exception as e:
            logging.error(f"Error registering service to Nacos: {e}")


    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    thread = ThreadPoolExecutor(max_workers=1)
    thread.submit(update_progress)

    # start http server
    try:
        logging.info("RAGFlow HTTP server start...")
        run_simple(
            hostname=settings.HOST_IP,
            port=settings.HOST_PORT,
            application=app,
            threaded=True,
            use_reloader=RuntimeConfig.DEBUG,
            use_debugger=RuntimeConfig.DEBUG,
        )
    except Exception:
        traceback.print_exc()
        stop_event.set()
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGKILL)
