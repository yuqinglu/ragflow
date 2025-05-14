import time

class Snowflake:
    def __init__(self, datacenter_id=0, worker_id=0):
        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.sequence = 0
        self.last_timestamp = -1

        # 2024-01-01 00:00:00 UTC+8
        self.epoch = 1704038400000  

    def generate_id(self):
        timestamp = int(time.time() * 1000)

        if timestamp < self.last_timestamp:
            raise Exception("Clock moved backwards")

        if timestamp == self.last_timestamp:
            self.sequence = (self.sequence + 1) & 0xFFF
            if self.sequence == 0:
                timestamp = self.wait_next_millis(self.last_timestamp)
        else:
            self.sequence = 0

        self.last_timestamp = timestamp

        return ((timestamp - self.epoch) << 22) | (self.datacenter_id << 18) | (self.worker_id << 12) | self.sequence

    def wait_next_millis(self, last_timestamp):
        timestamp = int(time.time() * 1000)
        while timestamp <= last_timestamp:
            timestamp = int(time.time() * 1000)
        return timestamp

# 初始化默认实例
snowflake_instance = Snowflake()

def generate_snowflake_id():
    return str(snowflake_instance.generate_id())