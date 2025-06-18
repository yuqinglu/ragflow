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
from concurrent.futures import ThreadPoolExecutor, as_completed

import logging
from PIL import Image

from rag.app.picture import vision_llm_chunk as picture_vision_llm_chunk
from rag.prompts import vision_llm_figure_describe_prompt


def vision_figure_parser_figure_data_wraper(figures_data_without_positions, context_window=5):
    """
    包装图片数据，同时收集上下文信息
    Args:
        figures_data_without_positions: 原始图片数据列表
        context_window: 上下文窗口大小，默认为5
    Returns:
        处理后的图片数据列表，每个图片数据包含图片、描述和位置信息
    """
    result = []
    
    # 首先收集所有文本段落，用于后续获取上下文
    all_texts = []
    for figure_data in figures_data_without_positions:
        if isinstance(figure_data[1], Image.Image):
            # 如果当前段落包含图片，记录其文本内容
            all_texts.append((figure_data[0], True))  # True表示包含图片
        else:
            # 普通文本段落
            all_texts.append((figure_data[0], False))
    
    # 处理每个图片数据
    for i, figure_data in enumerate(figures_data_without_positions):
        if not isinstance(figure_data[1], Image.Image):
            continue
            
        # 获取上下文信息
        context = []
        # 获取前文
        for j in range(max(0, i - context_window), i):
            if all_texts[j][1]:  # 如果前文包含图片，跳过
                continue
            context.append(all_texts[j][0])
            
        # 获取后文
        for j in range(i + 1, min(len(all_texts), i + context_window + 1)):
            if all_texts[j][1]:  # 如果后文包含图片，跳过
                continue
            context.append(all_texts[j][0])
        
        # 创建图片数据对象，保持原有的数据结构
        # 将Caption和Context组合成一个字符串，使用特殊分隔符
        description_parts = []
        if figure_data[0]:
            description_parts.append(f"Caption: {figure_data[0]}")
        if context:
            description_parts.append(f"Context: {' '.join(context)}")
        
        description = " ||| ".join(description_parts)
        
        result.append((
            (figure_data[1], [description]),  # 图片和描述（包含Caption和Context）
            [(0, 0, 0, 0, 0)]  # 位置信息
        ))
    
    return result


def pdf_vision_figure_parser_figure_data_wraper(figures_data, sections, min_context_chars=800):
    """
    为PDF的图片数据包装上下文信息
    Args:
        figures_data: PDF中提取的图片数据列表，格式为 [(img, [caption]), positions]
        sections: PDF中的文本段落列表，格式为 [(text, line_tag), ...]
        min_context_chars: 本页文本的最小字符数阈值，默认为800，如果本页文本超过此阈值则优先使用本页
    Returns:
        处理后的图片数据列表，每个图片数据包含图片、描述和位置信息
    """
    if not figures_data or not sections:
        return figures_data
    
    result = []
    
    # 提取所有文本段落，建立页码到文本的映射
    page_text_map = {}
    for text, line_tag in sections:
        if not line_tag:
            continue
        try:
            # 解析line_tag获取页码信息
            # line_tag格式：@@page_num\t...##
            import re
            match = re.search(r'@@([0-9-]+)\t', line_tag)
            if match:
                page_nums = match.group(1).split('-')
                for page_num_str in page_nums:
                    page_num = int(page_num_str)
                    if page_num not in page_text_map:
                        page_text_map[page_num] = []
                    page_text_map[page_num].append(text.strip())
        except Exception as e:
            logging.warning(f"Failed to parse line_tag: {line_tag}, error: {e}")
            continue
    
    # 处理每个图片数据
    for item in figures_data:
        if len(item) != 2:
            result.append(item)
            continue
            
        img_desc, positions = item
        if len(img_desc) != 2:
            result.append(item)
            continue
            
        img, captions = img_desc
        if not positions:
            result.append(item)
            continue
            
        # 获取图片所在的页码（使用第一个位置的页码）
        img_page = positions[0][0] if positions[0] and len(positions[0]) > 0 else 1
        
        # 收集上下文文本，按优先级：本页 > 上一页 > 下一页
        context_texts = []
        
        # 1. 首先获取本页文本
        current_page_texts = []
        if img_page in page_text_map:
            current_page_texts = page_text_map[img_page]
            context_texts.extend(current_page_texts)
        
        # 检查本页文本长度，如果够多就优先使用本页
        current_page_text = " ".join(current_page_texts)
        if len(current_page_text) >= min_context_chars:
            context = current_page_text
            logging.debug(f"Figure on page {img_page}: Using current page context only ({len(current_page_text)} chars)")
            if len(context) > 2000:  # 限制上下文长度
                context = context[:2000] + "..."
        else:
            # 2. 本页文本不够，添加上一页文本
            prev_page = img_page - 1
            if prev_page in page_text_map:
                context_texts.extend(page_text_map[prev_page])
                logging.debug(f"Figure on page {img_page}: Added previous page {prev_page} context")
            
            # 3. 如果还不够，添加下一页文本
            next_page = img_page + 1
            if next_page in page_text_map:
                context_texts.extend(page_text_map[next_page])
                logging.debug(f"Figure on page {img_page}: Added next page {next_page} context")
            
            # 限制上下文长度，避免过长
            context = " ".join(context_texts)
            logging.debug(f"Figure on page {img_page}: Using multi-page context ({len(context)} chars)")
            if len(context) > 2000:  # 限制上下文长度
                context = context[:2000] + "..."
        
        # 组织描述信息
        description_parts = []
        if captions and any(captions):
            caption = " ".join([c for c in captions if c and c.strip()])
            if caption.strip():
                description_parts.append(f"Caption: {caption}")
        
        if context.strip():
            description_parts.append(f"Context: {context}")
        
        # 创建新的描述
        if description_parts:
            enhanced_description = " ||| ".join(description_parts)
        else:
            enhanced_description = captions[0] if captions else ""
        
        # 创建增强后的图片数据
        enhanced_item = (
            (img, [enhanced_description]),
            positions
        )
        
        result.append(enhanced_item)
    
    return result


shared_executor = ThreadPoolExecutor(max_workers=10)


class VisionFigureParser:
    def __init__(self, vision_model, figures_data, *args, **kwargs):
        self.vision_model = vision_model
        self._extract_figures_info(figures_data)
        assert len(self.figures) == len(self.descriptions)
        assert not self.positions or (len(self.figures) == len(self.positions))

    def _extract_figures_info(self, figures_data):
        self.figures = []
        self.descriptions = []
        self.positions = []
        self.contexts = []  # 存储每个图片的上下文信息
        self.captions = []  # 存储每个图片的真实caption
        self.filenames = {}  # 存储每个图片的文件名

        for item in figures_data:
            # position
            if len(item) == 2 and isinstance(item[0], tuple) and len(item[0]) == 2 and isinstance(item[1], list) and isinstance(item[1][0], tuple) and len(item[1][0]) == 5:
                img_desc = item[0]
                assert len(img_desc) == 2 and isinstance(img_desc[0], Image.Image) and isinstance(img_desc[1], list), "Should be (figure, [description])"
                self.figures.append(img_desc[0])
                self.descriptions.append(img_desc[1])
                self.positions.append(item[1])
                
                # 从描述中提取上下文信息和caption
                context = None
                caption = None
                for desc in img_desc[1]:
                    for part in desc.split(" ||| "):
                        if part.startswith("Context:"):
                            context = part[8:].strip()  # 移除"Context:"前缀
                        elif part.startswith("Caption:"):
                            caption = part[8:].strip()  # 移除"Caption:"前缀
                self.contexts.append(context)
                self.captions.append(caption)
            else:
                assert len(item) == 2 and isinstance(item[0], Image.Image) and isinstance(item[1], list), f"Unexpected form of figure data: get {len(item)=}, {item=}"
                self.figures.append(item[0])
                self.descriptions.append(item[1])
                
                # 从描述中提取上下文信息和caption
                context = None
                caption = None
                for desc in item[1]:
                    for part in desc.split(" ||| "):
                        if part.startswith("Context:"):
                            context = part[8:].strip()  # 移除"Context:"前缀
                        elif part.startswith("Caption:"):
                            caption = part[8:].strip()  # 移除"Caption:"前缀
                self.contexts.append(context)
                self.captions.append(caption)

    def _assemble(self):
        self.assembled = []
        self.has_positions = len(self.positions) != 0

        for i in range(len(self.figures)):
            figure = self.figures[i]
            desc = self.descriptions[i]
            filename = self.filenames[i]
            pos = self.positions[i] if self.has_positions else [(0, 0, 0, 0, 0)]

            # 过滤掉desc或filename为空的成员
            if not desc or not any(desc) or not filename:
                continue

            # 保持与figures_data相同的结构
            self.assembled.append((
                (figure, desc, filename),  # 图片和描述
                pos  # 位置信息
            ))

        return self.assembled

    def __call__(self, **kwargs):
        callback = kwargs.get("callback", lambda prog, msg: None)

        def process(figure_idx, figure_binary):
            # 构建增强的提示词
            context = self.contexts[figure_idx]
            caption = self.captions[figure_idx]  # 使用真实的caption
            
            enhanced_prompt = vision_llm_figure_describe_prompt()
            if context:
                enhanced_prompt += f"\n\n上下文信息：\n{context}"
            if caption:
                enhanced_prompt += f"\n\n图片标题：\n{caption}"

            description_text = picture_vision_llm_chunk(
                binary=figure_binary,
                vision_model=self.vision_model,
                prompt=enhanced_prompt,
                callback=callback,
            )
            
            # 处理大模型的返回结果
            if description_text == "LOW_CONFIDENCE":
                return figure_idx, "", ""
                
            # 尝试提取置信度和描述
            try:
                # 去除开头和结尾的空白字符
                description_text = description_text.strip()
                description_arr = description_text.split('\n')
                
                # 确保数组不为空且第一个元素包含置信度信息
                if not description_arr or 'Confidence:' not in description_arr[0]:
                    logging.warning(f"Invalid description format: {description_text}")
                    return figure_idx, "", ""
                    
                confidence_line = description_arr[0]
                confidence = int(confidence_line.split(':')[1].strip())
                
                if confidence < 75:
                    return figure_idx, "", ""
                    
                # 提取描述部分
                description = description_arr[1].split(':')[1].strip()
                filename = description_arr[2].split(':')[1].strip()
                return figure_idx, description, filename
            except Exception as e:
                logging.error(f"Error parsing description: {e}, description_text: {description_text}")
                # 如果解析失败，返回空字符串
                return figure_idx, "", ""

        futures = []
        for idx, img_binary in enumerate(self.figures or []):
            futures.append(shared_executor.submit(process, idx, img_binary))

        for future in as_completed(futures):
            figure_num, txt, filename = future.result()
            # 直接使用大模型的描述，不再与原有信息拼接
            self.descriptions[figure_num] = [txt]
            self.filenames[figure_num] = filename

        self._assemble()

        return self.assembled
