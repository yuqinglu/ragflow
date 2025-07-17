#!/bin/bash
export LANG=zh_CN.UTF-8
export LD_PRELOAD=/home/luyuqing/jemalloc/lib/libjemalloc.so.2
echo $LD_PRELOAD
#配置debug模式
#export LOG_LEVELS="root=DEBUG"

export PYTHONPATH=$(pwd)
nohup python rag/svr/task_executor.py 1 &