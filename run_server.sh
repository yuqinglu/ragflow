#!/bin/bash
export LANG=zh_CN.UTF-8
export LD_LIBRARY_PATH="$HOME/local/openssl/lib64:$LD_LIBRARY_PATH"
export DOC_ENGINE=elasticsearch
export NACOS_ENABLED=true
export NACOS_SERVER_ADDRESSES=mse-14722772-nacos-ans.mse.aliyuncs.com:8848
# 配置debug模式
# export LOG_LEVELS="root=DEBUG"

export PYTHONPATH=$(pwd)

nohup python api/ragflow_server.py &
