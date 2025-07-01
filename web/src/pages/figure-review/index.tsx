import React, { useState, useEffect } from 'react';
import { Card, Pagination, Spin, message, Image, Typography, Row, Col, Empty } from 'antd';
import { getFigures, FigureData } from '@/services/figure-service';
import './index.less';

const { Title, Text, Paragraph } = Typography;

const FigureReview: React.FC = () => {
  const [figures, setFigures] = useState<FigureData[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [total, setTotal] = useState<number>(0);
  const pageSize = 4;

  const fetchFigures = async (page: number) => {
    setLoading(true);
    try {
      const response = await getFigures(page, pageSize);
      if (response.code === 0 && response.data) {
        setFigures(response.data.figures);
        setTotal(response.data.total);
      } else {
        message.error('获取图片数据失败');
      }
    } catch (error) {
      console.error('获取图片数据失败:', error);
      message.error('获取图片数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFigures(currentPage);
  }, [currentPage]);

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  const formatDate = (dateString: string) => {
    try {
      return new Date(dateString).toLocaleString('zh-CN');
    } catch {
      return dateString;
    }
  };

  const renderFigureCard = (figure: FigureData) => (
    <Col span={12} key={figure.id}>
      <Card 
        className="figure-card"
        hoverable
        cover={
          <div className="figure-image-container">
            <Image
              src={figure.image_url}
              alt={figure.image_name || `图片 ${figure.id}`}
              placeholder={<div className="image-placeholder">加载中...</div>}
              fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAMIAAADDCAYAAADQvc6UAAABRWlDQ1BJQ0MgUHJvZmlsZQAAKJFjYGASSSwoyGFhYGDIzSspCnJ3UoiIjFJgf8LAwSDCIMogwMCcmFxc4BgQ4ANUwgCjUcG3awyMIPqyLsis7PPOq3QdDFcvjV3jOD1boQVTPQrgSkktTgbSf4A4LbmgqISBgTEFyFYuLykAsTuAbJEioKOA7DkgdjqEvQHEToKwj4DVhAQ5A9k3gGyB5IxEoBmML4BsnSQk8XQkNtReEOBxcfXxUQg1Mjc0dyHgXNJBSWpFCYh2zi+oLMpMzyhRcASGUqqCZ16yno6CkYGRAQMDKMwhqj/fAIcloxgHQqxAjIHBEugw5sUIsSQpBobtQPdLciLEVJYzMPBHMDBsayhILEqEO4DxG0txmrERhM29nYGBddr//5/DGRjYNRkY/l7////39v///y4Dmn+LgeHANwDrkl1AuO+pmgAAADhlWElmTU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAAAqACAAQAAAABAAAAwqADAAQAAAABAAAAwwAAAAD9b/HnAAAHlklEQVR4Ae3dP3Pu3BUG8A2b2V9gF2MZAIoQKKPFjwAAAAANFtgAAADlgR9gAAAAgAfKPbvqIq7bwWWmHO+97zqvPpgPPHnWkXhxzc="
              className="figure-image"
            />
          </div>
        }
      >
        <div className="figure-info">
          <div className="figure-ids">
            <Text strong>ID: </Text>
            <Text copyable className="figure-id">{figure.id}</Text>
          </div>
          <div className="figure-ids">
            <Text strong>图片ID: </Text>
            <Text copyable className="figure-id">{figure.img_id}</Text>
          </div>
          {figure.file_name && (
            <div className="figure-field">
              <Text strong>文件名: </Text>
              <Text>{figure.file_name}</Text>
            </div>
          )}
          {figure.image_name && (
            <div className="figure-field">
              <Text strong>图片名: </Text>
              <Text>{figure.image_name}</Text>
            </div>
          )}
          <div className="figure-field">
            <Text strong>创建时间: </Text>
            <Text>{formatDate(figure.create_time)}</Text>
          </div>
          {figure.content && (
            <div className="figure-content">
              <Text strong>内容描述:</Text>
              <Paragraph 
                ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}
                className="content-text"
              >
                {figure.content}
              </Paragraph>
            </div>
          )}
        </div>
      </Card>
    </Col>
  );

  return (
    <div className="figure-review-container">
      <div className="figure-review-header">
        <Title level={2}>图片审核系统</Title>
        <Text type="secondary">
          总共 {total} 张图片，当前第 {currentPage} 页，本页显示 {figures.length} 张图片
        </Text>
      </div>

      <Spin spinning={loading}>
        {figures.length > 0 ? (
          <Row gutter={[16, 32]} className="figure-grid">
            {figures.map(renderFigureCard)}
          </Row>
        ) : (
          !loading && (
            <Empty 
              description="暂无图片数据" 
              className="empty-state"
            />
          )
        )}
      </Spin>

      {total > 0 && (
        <div className="pagination-container">
          <Pagination
            current={currentPage}
            pageSize={pageSize}
            total={total}
            onChange={handlePageChange}
            showSizeChanger={false}
            showQuickJumper
            showTotal={(total, range) => 
              `第 ${range[0]}-${range[1]} 条，共 ${total} 条`
            }
          />
        </div>
      )}
    </div>
  );
};

export default FigureReview; 