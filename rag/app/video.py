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

import re
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional
from copy import deepcopy
from io import BytesIO

from PIL import Image
from api.db import LLMType
from rag.nlp import rag_tokenizer, naive_merge, tokenize
from api.db.services.llm_service import LLMBundle
from deepdoc.parser.video_parser import RAGFlowVideoParser, KeyframeStrategy
from deepdoc.parser.figure_parser import VisionFigureParser


@dataclass
class VideoProcessConfig:
    """视频处理配置"""
    chunk_token_num: int = 2048
    max_keyframes: int = 5
    analyze_frames: bool = False
    context_window: float = 30.0
    keyframe_strategy: str = "smart"
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'VideoProcessConfig':
        """从字典创建配置对象"""
        return cls(
            chunk_token_num=int(config_dict.get("chunk_token_num", 2048)),
            max_keyframes=config_dict.get("max_keyframes", 5),
            analyze_frames=config_dict.get("analyze_frames", False),
            context_window=config_dict.get("context_window", 30.0),
            keyframe_strategy=config_dict.get("keyframe_strategy", "smart")
        )


@dataclass
class VideoChunk:
    """视频块数据"""
    content: str
    doc_type_kwd: str
    start_time: float = 0.0
    end_time: float = 0.0
    timestamp: Optional[float] = None
    image: Optional[Image.Image] = None
    audio_context: str = ""


class VideoProcessor:
    """视频处理器，封装视频处理逻辑"""
    
    # 常量
    SENTENCE_DELIMITERS = r'[。！？；.!?;]'
    PROGRESS_STAGES = {
        'parse': (0.1, 0.3),
        'transcribe': (0.4, 0.6),
        'analyze_frames': (0.7, 0.9),
        'finalize': (0.9, 1.0)
    }
    
    def __init__(self, config: VideoProcessConfig, tenant_id: str, lang: str):
        self.config = config
        self.tenant_id = tenant_id
        self.lang = lang
        self.is_english = lang.lower() == "english"
        self.video_parser = RAGFlowVideoParser()
    
    def process(self, filename: str, binary: bytes, callback=None) -> List[Dict[str, Any]]:
        """处理视频文件"""
        try:
            # 初始化基础文档
            base_doc = self._create_base_document(filename)
            
            # 1. 解析视频
            self._update_progress(callback, 'parse', 0.0, "开始解析视频文件...")
            video_data = self._parse_video(binary)
            self._update_progress(callback, 'parse', 1.0, 
                                f"视频解析完成，时长{video_data['duration']:.1f}秒，"
                                f"提取到{len(video_data['keyframes'])}个关键帧")
            
            # 2. 语音转文本
            transcription = self._transcribe_audio(video_data['audio_data'], callback)
            
            # 3. 处理文本块
            text_chunks = self._process_text_chunks(transcription, video_data)
            
            # 4. 处理关键帧
            frame_chunks = self._process_frame_chunks(video_data, transcription, callback)
            
            # 5. 生成最终文档块
            self._update_progress(callback, 'finalize', 0.0, "生成文档块...")
            result_chunks = self._create_document_chunks(base_doc, text_chunks, frame_chunks, video_data)
            
            self._update_progress(callback, 'finalize', 1.0, f"视频处理完成，生成{len(result_chunks)}个知识块")
            return result_chunks
            
        except Exception as e:
            error_msg = f"视频处理失败: {str(e)}"
            logging.error(error_msg)
            if callback:
                callback(prog=-1, msg=error_msg)
            return []
    
    def _create_base_document(self, filename: str) -> Dict[str, Any]:
        """创建基础文档"""
        title_without_ext = re.sub(r"\.[a-zA-Z]+$", "", filename)
        title_tokens = rag_tokenizer.tokenize(title_without_ext)
        
        return {
            "docnm_kwd": filename,
            "title_tks": title_tokens,
            "title_sm_tks": rag_tokenizer.fine_grained_tokenize(title_tokens)
        }
    
    def _parse_video(self, binary: bytes) -> Dict[str, Any]:
        """解析视频，提取音频、关键帧和元数据"""
        # 提取音频
        audio_data = self.video_parser.extract_audio(binary)
        
        # 转换策略并提取关键帧
        try:
            strategy_enum = KeyframeStrategy(self.config.keyframe_strategy)
        except ValueError:
            strategy_enum = KeyframeStrategy.SMART
        
        keyframes_with_timestamps = self.video_parser.extract_keyframes_with_timestamps(
            binary, self.config.max_keyframes, strategy_enum
        )
        
        # 将关键帧数据从bytes转换为PIL.Image对象，并保持与时间戳的对应关系
        pil_keyframes = []
        valid_timestamps = []
        for frame_data, timestamp in keyframes_with_timestamps:
            try:
                pil_image = Image.open(BytesIO(frame_data))
                pil_keyframes.append(pil_image)
                valid_timestamps.append(timestamp)
            except Exception as e:
                logging.warning(f"Failed to convert keyframe at {timestamp}s to PIL.Image: {e}")
                # 转换失败时跳过该帧
                continue
        
        # 获取元数据
        metadata_obj = self.video_parser.get_video_metadata(binary)
        
        return {
            'audio_data': audio_data,
            'keyframes': pil_keyframes,
            'timestamps': valid_timestamps,
            'duration': metadata_obj.duration,
            'metadata': metadata_obj
        }
    
    def _transcribe_audio(self, audio_data: bytes, callback=None) -> str:
        """语音转文本"""
        if not audio_data:
            return ""
        
        try:
            self._update_progress(callback, 'transcribe', 0.0, "开始语音转文本...")
            seq2txt_mdl = LLMBundle(self.tenant_id, LLMType.SPEECH2TEXT, lang=self.lang)
            logging.info(f"DEBUG: seq2txt_mdl: {seq2txt_mdl}, model_name: {seq2txt_mdl.mdl.model_name}")
            transcription = seq2txt_mdl.transcription(audio_data)
            # 确保transcription是字符串类型
            if not isinstance(transcription, str):
                transcription = str(transcription) if transcription is not None else ""
            logging.info(f"语音转文本完成: {transcription}")
            self._update_progress(callback, 'transcribe', 1.0, f"语音转文本完成: {transcription[:50]}...")
            return transcription
        except Exception as e:
            logging.error(f"语音转文本失败: {e}")
            return ""
    
    def _process_text_chunks(self, transcription: str, video_data: Dict[str, Any]) -> List[VideoChunk]:
        """处理语音转录文本块"""
        logging.info(f"DEBUG: transcription is {transcription}， self.config.chunk_token_num is {self.config.chunk_token_num}")
        if not transcription:
            return []
        
        # 按句子分割并合并（基于token数分块）
        sentences = re.split(self.SENTENCE_DELIMITERS, transcription)
        sentences = [(s.strip(), "") for s in sentences if s.strip()]
        merged_chunks = naive_merge(sentences, self.config.chunk_token_num)
        
        text_chunks = []
        duration = video_data['duration']
        
        # 始终按token数分块，不考虑关键帧时间
        for chunk_text in merged_chunks:
            if chunk_text.strip():
                text_chunks.append(VideoChunk(
                    content=chunk_text.strip(),
                    doc_type_kwd="audio_chunk",
                    start_time=0.0,
                    end_time=duration
                ))
        logging.info(f"DEBUG: text_chunks is {text_chunks}")
        return text_chunks
    
    def _process_frame_chunks(self, video_data: Dict[str, Any], transcription: str, 
                            callback=None) -> List[VideoChunk]:
        """处理关键帧块"""
        logging.info(f"start to process frame chunks")
        if not (video_data['keyframes']):
            return []
        
        frame_chunks = []
        keyframes = video_data['keyframes']
        timestamps = video_data['timestamps']
        duration = video_data['duration']
        
        try:
            self._update_progress(callback, 'analyze_frames', 0.0, "开始分析关键帧...")
            
            # 获取视觉模型
            vision_mdl = LLMBundle(self.tenant_id, LLMType.IMAGE2TEXT, lang=self.lang)
            
            # 准备VisionFigureParser所需的数据格式
            figures_data = []
            for i, (pil_image, timestamp) in enumerate(zip(keyframes, timestamps)):
                # 提取语音上下文
                audio_context = self._extract_audio_context(transcription, timestamp, duration)
                
                # 构建描述信息（包含时间戳和音频上下文）
                description_parts = []
                description_parts.append(f"Caption: 视频关键帧，时间：{timestamp:.1f}秒")
                if audio_context:
                    description_parts.append(f"Context: {audio_context}")
                
                description = " ||| ".join(description_parts)
                
                # 添加到figures_data，格式：(PIL.Image, [description])
                figures_data.append((pil_image, [description]))
                logging.info(f"DEBUG: figures_data is {figures_data[-1]}")
            
            # 使用VisionFigureParser进行分析
            if figures_data:
                logging.info(f"Processing {len(figures_data)} keyframes with VisionFigureParser")
                figure_parser = VisionFigureParser(
                    vision_model=vision_mdl,
                    figures_data=figures_data
                )
                
                # 调用figure_parser进行处理
                processed_figures = figure_parser(callback=callback)
                logging.info(f"VisionFigureParser processing completed, got {len(processed_figures)} results")
                
                # 使用单独的函数处理VisionFigureParser的结果
                frame_chunks = self._process_vision_results(
                    processed_figures, keyframes, timestamps, transcription, duration, callback
                )
                logging.info(f"DEBUG: frame_chunks is {frame_chunks}")
            
        except Exception as e:
            logging.error(f"视觉模型不可用，跳过关键帧分析: {e}")
            # 如果VisionFigureParser失败，不创建任何关键帧块
            frame_chunks = []
        
        return frame_chunks
    
    def _process_vision_results(self, processed_figures: List[Any], keyframes: List[Any], 
                               timestamps: List[float], transcription: str, duration: float, 
                               callback=None) -> List[VideoChunk]:
        """处理VisionFigureParser的结果，生成VideoChunk列表"""
        frame_chunks = []
        
        logging.info(f"Processing {len(processed_figures)} vision results for {len(keyframes)} keyframes")
        
        # 创建一个映射，从图像对象到处理结果
        processed_dict = {}
        for processed_figure in processed_figures:
            try:
                if isinstance(processed_figure, tuple) and len(processed_figure) >= 1:
                    content = processed_figure[0]
                    if isinstance(content, tuple) and len(content) >= 1:
                        image_data = content[0]
                        processed_dict[id(image_data)] = processed_figure
            except Exception as e:
                logging.warning(f"Error mapping processed figure: {e}")
        
        # 只为VisionFigureParser成功处理的关键帧创建VideoChunk
        processed_count = 0
        total_keyframes = len(keyframes)
        
        for i, (pil_image, timestamp) in enumerate(zip(keyframes, timestamps)):
            audio_context = self._extract_audio_context(transcription, timestamp, duration)
            
            # 检查这个图像是否被VisionFigureParser成功处理
            image_id = id(pil_image)
            
            if image_id in processed_dict:
                # 提取VisionFigureParser处理后的描述
                try:
                    processed_figure = processed_dict[image_id]
                    content = processed_figure[0]
                    if isinstance(content, tuple) and len(content) >= 2:
                        descriptions = content[1]
                        if isinstance(descriptions, list) and descriptions and descriptions[0]:
                            description = descriptions[0].strip()
                            # 只有当描述有效且不为空时才创建chunk
                            if description:
                                frame_chunks.append(VideoChunk(
                                    content=description,
                                    doc_type_kwd="keyframe",
                                    timestamp=timestamp,
                                    image=pil_image,
                                    audio_context=audio_context
                                ))
                                processed_count += 1
                                logging.debug(f"Created chunk for keyframe {i} with description: {description[:100]}...")
                            else:
                                logging.debug(f"Skipping keyframe {i}: empty description from VisionFigureParser")
                        else:
                            logging.debug(f"Skipping keyframe {i}: no valid descriptions from VisionFigureParser")
                    else:
                        logging.debug(f"Skipping keyframe {i}: invalid content format from VisionFigureParser")
                except Exception as e:
                    logging.warning(f"Skipping keyframe {i}: error extracting VisionFigureParser description: {e}")
            else:
                logging.debug(f"Skipping keyframe {i}: not processed by VisionFigureParser")
            
            # 更新进度
            if callback:
                progress = (i + 1) / total_keyframes
                self._update_progress(callback, 'analyze_frames', progress, 
                                    f"处理关键帧 {i+1}/{total_keyframes}，生成{processed_count}个有效块")
        
        logging.info(f"Successfully processed {processed_count} out of {total_keyframes} keyframes")
        return frame_chunks
    
    def _create_document_chunks(self, base_doc: Dict[str, Any], text_chunks: List[VideoChunk], 
                              frame_chunks: List[VideoChunk], video_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """创建最终的文档块"""
        result_chunks = []
        
        # 处理文本块
        for chunk in text_chunks:
            doc = self._create_chunk_document(base_doc, chunk, "video_audio")
            result_chunks.append(doc)
        
        # 处理关键帧块
        for chunk in frame_chunks:
            doc = self._create_frame_document(base_doc, chunk)
            result_chunks.append(doc)
        
        logging.info(f"DEBUG: result_chunks is {result_chunks}")
        return result_chunks
    
    def _create_chunk_document(self, base_doc: Dict[str, Any], chunk: VideoChunk, 
                             doc_type: str) -> Dict[str, Any]:
        """创建文本块文档"""
        doc = deepcopy(base_doc)
        
        # 将时间信息编码到内容中
        content = chunk.content
        if chunk.start_time is not None:
            content = f"[{chunk.start_time:.1f}s-{chunk.end_time:.1f}s] {content}"
        
        tokenize(doc, content, self.is_english)
        doc.update({
            "doc_type_kwd": doc_type
        })
        
        return doc
    
    def _create_frame_document(self, base_doc: Dict[str, Any], chunk: VideoChunk) -> Dict[str, Any]:
        """创建关键帧文档"""
        doc = deepcopy(base_doc)
        
        # 只使用大模型返回的纯文本，不添加其他内容
        content = chunk.content
        tokenize(doc, content, self.is_english)
        
        doc.update({
            "doc_type_kwd": "video_frame",
            "image": chunk.image
        })
        
        return doc
    
    def _extract_audio_context(self, transcription: str, timestamp: float, 
                             duration: float) -> str:
        """为关键帧提取语音上下文"""
        if not transcription or duration <= 0:
            return ""
        
        # 计算上下文范围
        half_window = self.config.context_window / 2
        start_time = max(0.0, timestamp - half_window)
        end_time = min(duration, timestamp + half_window)
        
        # 转换为文本位置
        chars_per_second = len(transcription) / duration
        start_pos = int(start_time * chars_per_second)
        end_pos = int(end_time * chars_per_second)
        
        # 边界检查
        start_pos = max(0, min(start_pos, len(transcription)))
        end_pos = max(start_pos, min(end_pos, len(transcription)))
        
        context = transcription[start_pos:end_pos]
        
        # 优化边界，避免截断句子
        return self._optimize_text_boundaries(transcription, context, start_pos, end_pos)
    
    def _optimize_text_boundaries(self, full_text: str, context: str, 
                                start_pos: int, end_pos: int) -> str:
        """优化文本边界，避免截断句子"""
        # 向前找句子开始
        if start_pos > 0:
            for i in range(start_pos, max(0, start_pos - 50), -1):
                if full_text[i] in '。！？；.!?;':
                    context = full_text[i+1:end_pos]
                    break
        
        # 向后找句子结束
        if end_pos < len(full_text):
            for i in range(end_pos, min(len(full_text), end_pos + 50)):
                if full_text[i] in '。！？；.!?;':
                    context = context[:i-end_pos+len(context)+1]
                    break
        
        return context.strip()
    
    def _segment_by_timestamps(self, transcription: str, duration: float, 
                             timestamps: List[float]) -> List[Tuple[str, float, float]]:
        """根据时间戳分割转录文本"""
        if not transcription or not timestamps:
            return [(transcription, 0.0, duration)]
        
        # 构建时间点列表
        time_points = [0.0] + sorted(timestamps) + [duration]
        chars_per_second = len(transcription) / duration if duration > 0 else 0
        
        segments = []
        for i in range(len(time_points) - 1):
            start_time, end_time = time_points[i], time_points[i + 1]
            
            if chars_per_second > 0:
                start_pos = int(start_time * chars_per_second)
                end_pos = int(end_time * chars_per_second)
                start_pos = max(0, min(start_pos, len(transcription)))
                end_pos = max(start_pos, min(end_pos, len(transcription)))
                segment_text = transcription[start_pos:end_pos].strip()
            else:
                # 平均分割
                segment_size = len(transcription) // (len(time_points) - 1)
                start_pos = i * segment_size
                end_pos = (i + 1) * segment_size if i < len(time_points) - 2 else len(transcription)
                segment_text = transcription[start_pos:end_pos].strip()
            
            if segment_text:
                segments.append((segment_text, start_time, end_time))
        
        return segments
    
    def _update_progress(self, callback, stage: str, progress: float, message: str) -> None:
        """更新进度"""
        if not callback:
            return
        
        start, end = self.PROGRESS_STAGES[stage]
        actual_progress = start + (end - start) * progress
        callback(actual_progress, message)


def chunk(filename: str, binary: bytes, tenant_id: str, lang: str, 
          callback=None, **kwargs) -> List[Dict[str, Any]]:
    """
    视频文件分块处理函数
    
    Args:
        filename: 视频文件名
        binary: 视频文件二进制数据
        tenant_id: 租户ID
        lang: 语言设置
        callback: 进度回调函数
        **kwargs: 其他参数
        
    Returns:
        处理后的文档块列表
    """
    # 解析配置
    parser_config = kwargs.get("parser_config", {})
    logging.info(f"video chunk parser_config is {parser_config}")
    config = VideoProcessConfig.from_dict(parser_config)
    
    # 创建处理器并处理
    processor = VideoProcessor(config, tenant_id, lang)
    return processor.process(filename, binary, callback)


 