import { useTranslate } from '@/hooks/common-hooks';
import { IModalProps } from '@/interfaces/common';
import { InboxOutlined } from '@ant-design/icons';
import {
  Checkbox,
  Flex,
  Modal,
  Progress,
  Segmented,
  Tabs,
  TabsProps,
  Upload,
  UploadFile,
  UploadProps,
  Form,
  Input,
} from 'antd';
import { Dispatch, SetStateAction, useState } from 'react';

import styles from './index.less';

const { Dragger } = Upload;

const FileUpload = ({
  directory,
  fileList,
  setFileList,
  uploadProgress,
}: {
  directory: boolean;
  fileList: UploadFile[];
  setFileList: Dispatch<SetStateAction<UploadFile[]>>;
  uploadProgress?: number;
}) => {
  const { t } = useTranslate('fileManager');
  const props: UploadProps = {
    multiple: true,
    onRemove: (file) => {
      const index = fileList.indexOf(file);
      const newFileList = fileList.slice();
      newFileList.splice(index, 1);
      setFileList(newFileList);
    },
    beforeUpload: (file: UploadFile) => {
      setFileList((pre) => {
        return [...pre, file];
      });

      return false;
    },
    directory,
    fileList,
    progress: {
      strokeWidth: 2,
    },
  };

  return (
    <>
      <Progress percent={uploadProgress} showInfo={false} />
      <Dragger {...props} className={styles.uploader}>
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">{t('uploadTitle')}</p>
        <p className="ant-upload-hint">{t('uploadDescription')}</p>
        {false && <p className={styles.uploadLimit}>{t('uploadLimit')}</p>}
      </Dragger>
    </>
  );
};

interface IFileUploadModalProps
  extends IModalProps<
    { parseOnCreation: boolean; directoryFileList: UploadFile[] } | UploadFile[]
  > {
  uploadFileList?: UploadFile[];
  setUploadFileList?: Dispatch<SetStateAction<UploadFile[]>>;
  uploadProgress?: number;
  setUploadProgress?: Dispatch<SetStateAction<number>>;
}

const FileUploadModal = ({
  visible,
  hideModal,
  loading,
  onOk: onFileUploadOk,
  uploadFileList: fileList,
  setUploadFileList: setFileList,
  uploadProgress,
  setUploadProgress,
}: IFileUploadModalProps) => {
  const { t } = useTranslate('fileManager');
  const [value, setValue] = useState<string | number>('local');
  const [parseOnCreation, setParseOnCreation] = useState(false);
  const [isMicroCourse, setIsMicroCourse] = useState(false);
  const [currentFileList, setCurrentFileList] = useState<UploadFile[]>([]);
  const [directoryFileList, setDirectoryFileList] = useState<UploadFile[]>([]);
  const [form] = Form.useForm();

  const clearFileList = () => {
    if (setFileList) {
      setFileList([]);
      setUploadProgress?.(0);
    } else {
      setCurrentFileList([]);
    }
    setDirectoryFileList([]);
    form.resetFields();
    setIsMicroCourse(false);
  };

  const onOk = async () => {
    if (uploadProgress === 100) {
      hideModal?.();
      return;
    }

    const formValues = await form.validateFields();
    const metadata = isMicroCourse ? {
      is_micro_course: true,
      micro_course_id: formValues.micro_course_id,
      micro_course_name: formValues.micro_course_name,
      micro_course_desc: formValues.micro_course_desc,
      course_id: formValues.course_id,
      course_name: formValues.course_name,
      package_id: formValues.package_id,
      package_name: formValues.package_name,
    } : {};

    const ret = await onFileUploadOk?.(
      fileList
        ? { 
            parseOnCreation, 
            directoryFileList, 
            metadata: JSON.stringify(metadata)
          }
        : [...currentFileList, ...directoryFileList],
    );
    return ret;
  };

  const afterClose = () => {
    clearFileList();
  };

  const items: TabsProps['items'] = [
    {
      key: '1',
      label: t('file'),
      children: (
        <FileUpload
          directory={false}
          fileList={fileList ? fileList : currentFileList}
          setFileList={setFileList ? setFileList : setCurrentFileList}
          uploadProgress={uploadProgress}
        ></FileUpload>
      ),
    },
    {
      key: '2',
      label: t('directory'),
      children: (
        <FileUpload
          directory
          fileList={directoryFileList}
          setFileList={setDirectoryFileList}
          uploadProgress={uploadProgress}
        ></FileUpload>
      ),
    },
  ];

  return (
    <>
      <Modal
        title={t('uploadFile')}
        open={visible}
        onOk={onOk}
        onCancel={hideModal}
        confirmLoading={loading}
        afterClose={afterClose}
        width={800}
      >
        <Flex gap={'large'} vertical>
          <Segmented
            options={[
              { label: t('local'), value: 'local' },
              { label: t('s3'), value: 's3' },
            ]}
            block
            value={value}
            onChange={setValue}
          />
          {value === 'local' ? (
            <>
              <Flex gap={'middle'}>
                <Checkbox
                  checked={parseOnCreation}
                  onChange={(e) => setParseOnCreation(e.target.checked)}
                >
                  {t('parseOnCreation')}
                </Checkbox>
                <Checkbox
                  checked={isMicroCourse}
                  onChange={(e) => setIsMicroCourse(e.target.checked)}
                >
                  是否是微课
                </Checkbox>
              </Flex>
              {isMicroCourse && (
                <Form
                  form={form}
                  layout="vertical"
                  style={{ marginTop: 16 }}
                >
                  <Form.Item
                    name="micro_course_id"
                    label="微课ID"
                    rules={[{ required: true, message: '请输入微课ID' }]}
                  >
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="micro_course_name"
                    label="微课名称"
                    rules={[{ required: true, message: '请输入微课名称' }]}
                  >
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="micro_course_desc"
                    label="微课简介"
                    rules={[{ required: true, message: '请输入微课简介' }]}
                  >
                    <Input.TextArea />
                  </Form.Item>
                  <Form.Item
                    name="course_id"
                    label="课程ID"
                    rules={[{ required: true, message: '请输入课程ID' }]}
                  >
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="course_name"
                    label="课程名称"
                    rules={[{ required: true, message: '请输入课程名称' }]}
                  >
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="package_id"
                    label="课包ID"
                    rules={[{ required: true, message: '请输入课包ID' }]}
                  >
                    <Input />
                  </Form.Item>
                  <Form.Item
                    name="package_name"
                    label="课包名称"
                    rules={[{ required: true, message: '请输入课包名称' }]}
                  >
                    <Input />
                  </Form.Item>
                </Form>
              )}
              <Tabs defaultActiveKey="1" items={items} />
            </>
          ) : (
            t('comingSoon', { keyPrefix: 'common' })
          )}
        </Flex>
      </Modal>
    </>
  );
};

export default FileUploadModal;
