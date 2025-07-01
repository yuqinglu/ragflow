import request from '@/utils/request';

export interface FigureData {
  id: string;
  img_id: string;
  image_url: string;
  image_name?: string;
  content?: string;
  file_name?: string;
  create_time: string;
}

export interface FigureListResponse {
  code: number;
  message: string;
  data: {
    figures: FigureData[];
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
  };
}

// 获取figures列表
export const getFigures = async (page: number = 1, pageSize: number = 4): Promise<FigureListResponse> => {
  const response = await request.get(`/api/v1/figures/page/${page}/size/${pageSize}`);
  // umi-request with getResponse: true returns { data, response }
  return response.data;
};

export default {
  getFigures,
}; 