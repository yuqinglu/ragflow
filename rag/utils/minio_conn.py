#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
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

import logging
import time
from minio import Minio
from minio.error import S3Error
from io import BytesIO
from rag import settings
from rag.utils import singleton


@singleton
class RAGFlowMinio:
    def __init__(self):
        self.conn = None
        self.external_conn = None
        self.__open__()

    def __open__(self):
        try:
            if self.conn:
                self.__close__()
        except Exception:
            pass

        try:
            # 内部连接 - 用于文件操作
            # 直接使用配置文件中的host，不添加端口
            host = settings.MINIO["host"]
            
            self.conn = Minio(host,
                              access_key=settings.MINIO["user"],
                              secret_key=settings.MINIO["password"],
                              secure=True
                              )
            
            # 外部连接 - 用于生成预签名URL
            if "external_host" in settings.MINIO and settings.MINIO["external_host"]:
                external_host = settings.MINIO["external_host"]
                external_secure = settings.MINIO.get("external_secure", True)
                
                # 直接使用配置文件中的external_host，不添加端口
                self.external_conn = Minio(external_host,
                                          access_key=settings.MINIO["user"],
                                          secret_key=settings.MINIO["password"],
                                          secure=external_secure
                                          )
                logging.info(f"External MinIO connection configured: {external_host} (secure: {external_secure})")
            else:
                # 如果没有配置外部域名，使用内部连接
                self.external_conn = self.conn
                logging.info("No external MinIO host configured, using internal connection for presigned URLs")
                
        except Exception as e:
            logging.exception(f"Fail to connect to MinIO host: {settings.MINIO.get('host', 'unknown')}")
            logging.error(f"MinIO connection error: {str(e)}")

    def __close__(self):
        del self.conn
        self.conn = None
        if self.external_conn and self.external_conn != self.conn:
            del self.external_conn
        self.external_conn = None

    def health(self):
        bucket, fnm, binary = "txtxtxtxt1", "txtxtxtxt1", b"_t@@@1"
        if not self.conn.bucket_exists(bucket):
            self.conn.make_bucket(bucket)
        r = self.conn.put_object(bucket, fnm,
                                 BytesIO(binary),
                                 len(binary)
                                 )
        return r

    def put(self, bucket, fnm, binary):
        for attempt in range(3):
            try:
                if not self.conn.bucket_exists(bucket):
                    self.conn.make_bucket(bucket)

                r = self.conn.put_object(bucket, fnm,
                                         BytesIO(binary),
                                         len(binary)
                                         )
                return r
            except S3Error as e:
                logging.error(f"MinIO S3Error on attempt {attempt + 1}: {e.code} - {e.message}")
                if e.code == "AccessDenied":
                    logging.error(f"Access denied for bucket: {bucket}. Please check MinIO credentials and permissions.")
                    # 对于访问拒绝错误，不要重试
                    break
                elif attempt < 2:  # 最后一次尝试不重试
                    self.__open__()
                    time.sleep(1)
            except Exception as e:
                logging.exception(f"Fail to put {bucket}/{fnm} on attempt {attempt + 1}:")
                if attempt < 2:  # 最后一次尝试不重试
                    self.__open__()
                    time.sleep(1)

    def rm(self, bucket, fnm):
        try:
            self.conn.remove_object(bucket, fnm)
        except Exception:
            logging.exception(f"Fail to remove {bucket}/{fnm}:")

    def get(self, bucket, filename):
        for attempt in range(3):
            try:
                r = self.conn.get_object(bucket, filename)
                return r.read()
            except S3Error as e:
                logging.error(f"MinIO S3Error on get attempt {attempt + 1}: {e.code} - {e.message}")
                if e.code == "AccessDenied":
                    logging.error(f"Access denied for bucket: {bucket}. Please check MinIO credentials and permissions.")
                    break
                elif attempt < 2:
                    self.__open__()
                    time.sleep(1)
            except Exception as e:
                logging.exception(f"Fail to get {bucket}/{filename} on attempt {attempt + 1}")
                if attempt < 2:
                    self.__open__()
                    time.sleep(1)
        return

    def obj_exist(self, bucket, filename):
        try:
            if not self.conn.bucket_exists(bucket):
                return False
            if self.conn.stat_object(bucket, filename):
                return True
            else:
                return False
        except S3Error as e:
            if e.code in ["NoSuchKey", "NoSuchBucket", "ResourceNotFound"]:
                return False
            elif e.code == "AccessDenied":
                logging.error(f"Access denied checking object existence: {bucket}/{filename}")
                return False
        except Exception:
            logging.exception(f"obj_exist {bucket}/{filename} got exception")
            return False

    def get_presigned_url(self, bucket, fnm, expires, response_headers=None):
        for attempt in range(10):
            try:
                # 使用外部连接生成预签名URL
                return self.external_conn.get_presigned_url("GET", bucket, fnm, expires, response_headers=response_headers)
            except S3Error as e:
                logging.error(f"MinIO S3Error on presigned URL attempt {attempt + 1}: {e.code} - {e.message}")
                if e.code == "AccessDenied":
                    logging.error(f"Access denied generating presigned URL for: {bucket}/{fnm}")
                    break
                elif attempt < 9:
                    self.__open__()
                    time.sleep(1)
            except Exception as e:
                logging.exception(f"Fail to get_presigned {bucket}/{fnm} on attempt {attempt + 1}:")
                if attempt < 9:
                    self.__open__()
                    time.sleep(1)
        return

