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

import json
import logging
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple, Dict, Any, Union


class KeyframeStrategy(Enum):
    """关键帧提取策略枚举"""
    UNIFORM = "uniform"
    SCENE_CHANGE = "scene_change" 
    AUDIO_BASED = "audio_based"
    SMART = "smart"


@dataclass
class VideoMetadata:
    """视频元数据"""
    duration: float = 0.0
    size: int = 0
    bitrate: int = 0
    video_codec: Optional[str] = None
    video_width: Optional[int] = None
    video_height: Optional[int] = None
    video_fps: Optional[float] = None
    audio_codec: Optional[str] = None
    audio_sample_rate: Optional[int] = None
    audio_channels: Optional[int] = None


@dataclass 
class FrameCandidate:
    """关键帧候选"""
    timestamp: float
    method: str
    weight: float


class FFmpegError(Exception):
    """FFmpeg相关错误"""
    pass


class RAGFlowVideoParser:
    """
    视频文件解析器，支持MP4等格式的短视频
    主要功能：
    1. 提取视频中的音频流
    2. 智能提取关键帧
    3. 获取视频元数据
    """
    
    # 常量配置
    DEFAULT_AUDIO_SAMPLE_RATE = 16000
    DEFAULT_AUDIO_CHANNELS = 1
    DEFAULT_SCENE_THRESHOLD = 0.3
    DEFAULT_SILENCE_NOISE = "-30dB"
    DEFAULT_SILENCE_DURATION = 1
    DEFAULT_FRAME_QUALITY = 2
    
    def __init__(self):
        self._check_ffmpeg()
    
    def _check_ffmpeg(self) -> None:
        """检查ffmpeg和ffprobe是否可用"""
        for cmd in ['ffmpeg', 'ffprobe']:
            try:
                subprocess.run([cmd, '-version'], 
                             capture_output=True, check=True, timeout=10)
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                raise RuntimeError(f"{cmd} is required for video processing. "
                                 f"Please install FFmpeg first.")
    
    @contextmanager
    def _temp_video_file(self, video_binary: bytes):
        """创建临时视频文件的上下文管理器"""
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
            try:
                temp_file.write(video_binary)
                temp_file.flush()
                yield temp_file.name
            finally:
                try:
                    os.unlink(temp_file.name)
                except OSError:
                    pass
    
    def _run_ffmpeg_command(self, cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """安全执行FFmpeg命令"""
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=timeout,
                check=False  # 不自动抛出异常，手动处理
            )
            if result.returncode != 0:
                raise FFmpegError(f"FFmpeg command failed: {' '.join(cmd)}\n"
                                f"Error: {result.stderr}")
            return result
        except subprocess.TimeoutExpired:
            raise FFmpegError(f"FFmpeg command timed out: {' '.join(cmd)}")
        except Exception as e:
            raise FFmpegError(f"FFmpeg command error: {e}")
    
    def extract_audio(self, video_binary: bytes, output_format: str = 'wav') -> bytes:
        """
        从视频中提取音频
        
        Args:
            video_binary: 视频文件的二进制数据
            output_format: 输出音频格式 (wav, mp3)
            
        Returns:
            提取的音频二进制数据
            
        Raises:
            FFmpegError: FFmpeg处理失败
        """
        if not video_binary:
            raise ValueError("Video binary data is empty")
        
        with self._temp_video_file(video_binary) as video_path:
            with tempfile.NamedTemporaryFile(suffix=f'.{output_format}') as audio_temp:
                
                # 构建FFmpeg命令
                codec = 'pcm_s16le' if output_format == 'wav' else 'mp3'
                cmd = [
                    'ffmpeg', '-i', video_path,
                    '-vn',  # 不处理视频流
                    '-acodec', codec,
                    '-ar', str(self.DEFAULT_AUDIO_SAMPLE_RATE),
                    '-ac', str(self.DEFAULT_AUDIO_CHANNELS),
                    '-y',  # 覆盖输出文件
                    audio_temp.name
                ]
                
                self._run_ffmpeg_command(cmd)
                
                # 读取提取的音频数据
                with open(audio_temp.name, 'rb') as f:
                    return f.read()
    
    def get_video_duration(self, video_path: str) -> float:
        """获取视频时长"""
        cmd = [
            'ffprobe', '-v', 'quiet', '-show_entries', 
            'format=duration', '-of', 'csv=p=0', video_path
        ]
        
        try:
            result = self._run_ffmpeg_command(cmd)
            return float(result.stdout.strip())
        except (FFmpegError, ValueError) as e:
            logging.warning(f"Failed to get video duration: {e}")
            return 0.0
    
    def get_video_metadata(self, video_binary: bytes) -> VideoMetadata:
        """
        获取视频元数据信息
        
        Args:
            video_binary: 视频文件的二进制数据
            
        Returns:
            VideoMetadata对象
        """
        if not video_binary:
            return VideoMetadata()
        
        with self._temp_video_file(video_binary) as video_path:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', video_path
            ]
            
            try:
                result = self._run_ffmpeg_command(cmd)
                metadata_json = json.loads(result.stdout)
                
                # 解析元数据
                format_info = metadata_json.get('format', {})
                video_stream = None
                audio_stream = None
                
                for stream in metadata_json.get('streams', []):
                    codec_type = stream.get('codec_type')
                    if codec_type == 'video' and not video_stream:
                        video_stream = stream
                    elif codec_type == 'audio' and not audio_stream:
                        audio_stream = stream
                
                # 构建VideoMetadata对象
                fps = None
                if video_stream and video_stream.get('r_frame_rate'):
                    try:
                        fps = eval(video_stream['r_frame_rate'])
                    except (ValueError, ZeroDivisionError):
                        fps = None
                
                return VideoMetadata(
                    duration=float(format_info.get('duration', 0)),
                    size=int(format_info.get('size', 0)),
                    bitrate=int(format_info.get('bit_rate', 0)),
                    video_codec=video_stream.get('codec_name') if video_stream else None,
                    video_width=video_stream.get('width') if video_stream else None,
                    video_height=video_stream.get('height') if video_stream else None,
                    video_fps=fps,
                    audio_codec=audio_stream.get('codec_name') if audio_stream else None,
                    audio_sample_rate=int(audio_stream.get('sample_rate', 0)) if audio_stream else None,
                    audio_channels=int(audio_stream.get('channels', 0)) if audio_stream else None
                )
                
            except (FFmpegError, json.JSONDecodeError, ValueError) as e:
                logging.error(f"Failed to get video metadata: {e}")
                return VideoMetadata()
    
    def extract_frame_at_time(self, video_path: str, timestamp: float) -> Optional[bytes]:
        """
        在指定时间点提取单帧
        
        Args:
            video_path: 视频文件路径
            timestamp: 时间戳（秒）
            
        Returns:
            帧图片数据，失败时返回None
        """
        if timestamp < 0:
            return None
        
        with tempfile.NamedTemporaryFile(suffix='.jpg') as frame_temp:
            cmd = [
                'ffmpeg', '-ss', str(timestamp), 
                '-i', video_path,
                '-vframes', '1', 
                '-q:v', str(self.DEFAULT_FRAME_QUALITY),
                '-y', frame_temp.name
            ]
            
            try:
                self._run_ffmpeg_command(cmd)
                with open(frame_temp.name, 'rb') as f:
                    return f.read()
            except FFmpegError as e:
                logging.debug(f"Failed to extract frame at {timestamp}s: {e}")
                return None
    
    def _get_scene_change_times(self, video_path: str, max_frames: int) -> List[float]:
        """获取场景变化时间点"""
        cmd = [
            'ffmpeg', '-i', video_path,
            '-vf', f'select=gt(scene\\,{self.DEFAULT_SCENE_THRESHOLD})',
            '-vsync', 'vfr',
            '-f', 'null', '-'
        ]
        
        try:
            result = self._run_ffmpeg_command(cmd)
            times = self._parse_scene_times_from_output(result.stderr)
            return times[:max_frames]
        except FFmpegError as e:
            logging.debug(f"Scene change detection failed: {e}")
            return []
    
    def _get_silence_times(self, video_path: str, max_frames: int) -> List[float]:
        """获取静音段时间点"""
        cmd = [
            'ffmpeg', '-i', video_path,
            '-af', f'silencedetect=noise={self.DEFAULT_SILENCE_NOISE}:duration={self.DEFAULT_SILENCE_DURATION}',
            '-f', 'null', '-'
        ]
        
        try:
            result = self._run_ffmpeg_command(cmd)
            times = self._parse_silence_times_from_output(result.stderr)
            return times[:max_frames]
        except FFmpegError as e:
            logging.debug(f"Silence detection failed: {e}")
            return []
    
    def _parse_scene_times_from_output(self, stderr_output: str) -> List[float]:
        """从FFmpeg输出中解析场景变化时间点"""
        scene_times = []
        pattern = r'frame:\s*\d+\s+fps=[\d.]+\s+q=[\d.-]+\s+size=\s*\d+kB\s+time=([\d:\.]+)'
        
        for match in re.finditer(pattern, stderr_output):
            try:
                time_str = match.group(1)
                parts = time_str.split(':')
                if len(parts) == 3:
                    hours, minutes, seconds = parts
                    total_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                    scene_times.append(total_seconds)
            except (ValueError, IndexError):
                continue
        
        return sorted(scene_times)
    
    def _parse_silence_times_from_output(self, stderr_output: str) -> List[float]:
        """从FFmpeg输出中解析静音段时间点"""
        silence_times = []
        pattern = r'silence_end:\s*([\d.]+)'
        
        for match in re.finditer(pattern, stderr_output):
            try:
                silence_times.append(float(match.group(1)))
            except ValueError:
                continue
        
        return sorted(silence_times)
    
    def _generate_uniform_times(self, duration: float, max_frames: int) -> List[float]:
        """生成均匀分布的时间点"""
        if duration <= 0 or max_frames <= 0:
            return []
        
        if duration <= max_frames:
            return [float(i) for i in range(int(duration))]
        
        interval = duration / (max_frames + 1)
        return [interval * (i + 1) for i in range(max_frames)]
    
    def _select_best_timestamps(self, candidates: List[FrameCandidate], 
                              max_frames: int, duration: float) -> List[float]:
        """从候选时间点中选择最佳的关键帧时间"""
        if not candidates or max_frames <= 0:
            return []
        
        # 按时间排序
        candidates.sort(key=lambda x: x.timestamp)
        
        # 去重并合并相近的时间点
        merged = []
        time_threshold = duration / (max_frames * 3)
        
        for candidate in candidates:
            merged_idx = -1
            for i, existing in enumerate(merged):
                if abs(candidate.timestamp - existing.timestamp) < time_threshold:
                    if candidate.weight > existing.weight:
                        merged_idx = i
                    break
            
            if merged_idx >= 0:
                merged[merged_idx] = candidate
            else:
                merged.append(candidate)
        
        # 按权重排序，选择最佳时间点
        merged.sort(key=lambda x: x.weight, reverse=True)
        
        # 确保时间分布相对均匀
        selected = []
        min_interval = duration / (max_frames * 2)
        
        for candidate in merged:
            if len(selected) >= max_frames:
                break
            
            # 检查时间间隔
            if all(abs(candidate.timestamp - s) >= min_interval for s in selected):
                selected.append(candidate.timestamp)
        
        # 如果选择的帧数不够，用均匀采样补充
        if len(selected) < max_frames:
            uniform_times = self._generate_uniform_times(duration, max_frames)
            for uniform_time in uniform_times:
                if len(selected) >= max_frames:
                    break
                if all(abs(uniform_time - s) >= min_interval for s in selected):
                    selected.append(uniform_time)
        
        return sorted(selected)
    
    def extract_keyframes(self, video_binary: bytes, 
                         max_frames: int = 5, 
                         strategy: Union[str, KeyframeStrategy] = KeyframeStrategy.SMART) -> List[bytes]:
        """
        智能提取视频关键帧
        
        Args:
            video_binary: 视频文件的二进制数据
            max_frames: 最大提取帧数
            strategy: 提取策略
            
        Returns:
            关键帧图片数据列表
        """
        if not video_binary or max_frames <= 0:
            return []
        
        # 统一策略类型
        if isinstance(strategy, str):
            try:
                strategy = KeyframeStrategy(strategy)
            except ValueError:
                logging.warning(f"Unknown strategy {strategy}, using SMART")
                strategy = KeyframeStrategy.SMART
        
        with self._temp_video_file(video_binary) as video_path:
            duration = self.get_video_duration(video_path)
            if duration <= 0:
                return []
            
            # 根据策略获取时间点
            timestamps = self._get_timestamps_by_strategy(video_path, strategy, max_frames, duration)
            
            # 提取关键帧
            frames = []
            for timestamp in timestamps:
                frame_data = self.extract_frame_at_time(video_path, timestamp)
                if frame_data:
                    frames.append(frame_data)
            
            return frames
    
    def _get_timestamps_by_strategy(self, video_path: str, strategy: KeyframeStrategy, 
                                  max_frames: int, duration: float) -> List[float]:
        """根据策略获取时间戳"""
        if strategy == KeyframeStrategy.UNIFORM:
            return self._generate_uniform_times(duration, max_frames)
        
        elif strategy == KeyframeStrategy.SCENE_CHANGE:
            scene_times = self._get_scene_change_times(video_path, max_frames)
            return scene_times if scene_times else self._generate_uniform_times(duration, max_frames)
        
        elif strategy == KeyframeStrategy.AUDIO_BASED:
            silence_times = self._get_silence_times(video_path, max_frames)
            return silence_times if silence_times else self._generate_uniform_times(duration, max_frames)
        
        elif strategy == KeyframeStrategy.SMART:
            return self._get_smart_timestamps(video_path, max_frames, duration)
        
        else:
            return self._generate_uniform_times(duration, max_frames)
    
    def _get_smart_timestamps(self, video_path: str, max_frames: int, duration: float) -> List[float]:
        """智能策略获取时间戳"""
        candidates = []
        
        # 场景变化检测（权重0.4）
        scene_times = self._get_scene_change_times(video_path, max_frames * 2)
        candidates.extend([FrameCandidate(t, "scene", 0.4) for t in scene_times])
        
        # 音频变化检测（权重0.3）
        silence_times = self._get_silence_times(video_path, max_frames)
        candidates.extend([FrameCandidate(t, "audio", 0.3) for t in silence_times])
        
        # 均匀分布基线（权重0.3）
        uniform_times = self._generate_uniform_times(duration, max_frames)
        candidates.extend([FrameCandidate(t, "uniform", 0.3) for t in uniform_times])
        
        if not candidates:
            return self._generate_uniform_times(duration, max_frames)
        
        return self._select_best_timestamps(candidates, max_frames, duration)
    
    def extract_keyframes_with_timestamps(self, video_binary: bytes, 
                                        max_frames: int = 5,
                                        strategy: Union[str, KeyframeStrategy] = KeyframeStrategy.SMART) -> List[Tuple[bytes, float]]:
        """
        提取关键帧并返回时间戳
        
        Returns:
            [(frame_data, timestamp), ...]
        """
        if not video_binary or max_frames <= 0:
            return []
        
        # 统一策略类型
        if isinstance(strategy, str):
            try:
                strategy = KeyframeStrategy(strategy)
            except ValueError:
                strategy = KeyframeStrategy.SMART
        
        with self._temp_video_file(video_binary) as video_path:
            duration = self.get_video_duration(video_path)
            if duration <= 0:
                return []
            
            # 获取时间戳
            timestamps = self._get_timestamps_by_strategy(video_path, strategy, max_frames, duration)
            
            # 提取关键帧
            results = []
            for timestamp in timestamps:
                frame_data = self.extract_frame_at_time(video_path, timestamp)
                if frame_data:
                    results.append((frame_data, timestamp))
            
            return results
    
    def __call__(self, fnm: str, binary: Optional[bytes] = None, **kwargs) -> Tuple[bytes, List[bytes], Dict[str, Any]]:
        """
        主要解析接口，与其他解析器保持一致
        
        Args:
            fnm: 文件名或文件路径
            binary: 视频文件二进制数据
            
        Returns:
            tuple: (音频数据, 关键帧列表, 元数据字典)
        """
        if binary is None:
            with open(fnm, 'rb') as f:
                binary = f.read()
        
        try:
            # 提取音频
            audio_data = self.extract_audio(binary)
            
            # 提取关键帧
            max_frames = kwargs.get('max_frames', 3)
            strategy = kwargs.get('strategy', KeyframeStrategy.SMART)
            keyframes = self.extract_keyframes(binary, max_frames, strategy)
            
            # 获取元数据
            metadata_obj = self.get_video_metadata(binary)
            
            # 转换为字典格式以保持兼容性
            metadata = {
                'duration': metadata_obj.duration,
                'size': metadata_obj.size,
                'bitrate': metadata_obj.bitrate,
                'video': {
                    'codec': metadata_obj.video_codec,
                    'width': metadata_obj.video_width,
                    'height': metadata_obj.video_height,
                    'fps': metadata_obj.video_fps
                },
                'audio': {
                    'codec': metadata_obj.audio_codec,
                    'sample_rate': metadata_obj.audio_sample_rate,
                    'channels': metadata_obj.audio_channels
                }
            }
            
            return audio_data, keyframes, metadata
            
        except Exception as e:
            logging.error(f"Video parsing failed for {fnm}: {e}")
            return b'', [], {} 