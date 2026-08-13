"""S3 兼容存储封装（minio SDK）：endpoint 解析、对象读写。"""
import io
from pathlib import Path

from minio import Minio

from app.models import S3Config


def endpoint_parts(endpoint: str) -> tuple[str, bool]:
    """把配置里的 endpoint 拆成 (host[:port], secure)。

    支持 http:// / https:// 前缀；无前缀默认 https。
    """
    endpoint = endpoint.strip()
    if endpoint.startswith("http://"):
        return endpoint[len("http://") :], False
    if endpoint.startswith("https://"):
        return endpoint[len("https://") :], True
    return endpoint, True


class S3Storage:
    """基于 minio SDK 的 S3 兼容存储客户端，按当前配置即时创建。"""

    def __init__(self, cfg: S3Config, access_id: str, access_key: str) -> None:
        host, secure = endpoint_parts(cfg.endpoint)
        self.cfg = cfg
        self.bucket = cfg.bucket
        self._client = Minio(
            host,
            access_key=access_id,
            secret_key=access_key,
            secure=secure,
            region=cfg.region,
        )

    def upload_file(self, object_name: str, file_path: Path) -> None:
        """上传本地文件到 bucket 的指定对象；bucket 不存在/凭据错误/网络失败抛异常。"""
        self._client.fput_object(self.bucket, object_name, str(file_path))

    def bucket_exists(self) -> bool:
        """检查 bucket 是否存在（同时验证凭据与网络连通性）。"""
        return self._client.bucket_exists(self.bucket)

    def put_data(self, object_name: str, data: bytes) -> None:
        """写入字节数据到指定对象（覆盖）。"""
        self._client.put_object(
            self.bucket, object_name, io.BytesIO(data), length=len(data)
        )

    def get_data(self, object_name: str) -> bytes | None:
        """读取对象内容；对象不存在时返回 None，其他错误抛异常。"""
        from minio.error import S3Error

        try:
            resp = self._client.get_object(self.bucket, object_name)
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            raise
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def list_objects(self, prefix: str) -> list[str]:
        """列出指定前缀下的全部对象名（递归）。"""
        return [
            obj.object_name
            for obj in self._client.list_objects(self.bucket, prefix=prefix, recursive=True)
        ]
