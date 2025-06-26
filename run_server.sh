#!/bin/bash
export LANG=zh_CN.UTF-8
export LD_LIBRARY_PATH="$HOME/local/openssl/lib64:$LD_LIBRARY_PATH"
export DOC_ENGINE=infinity
# 配置debug模式
# export LOG_LEVELS="root=DEBUG"

export PYTHONPATH=$(pwd)

nohup python api/ragflow_server.py &
