"""
数据文件处理器：Excel / CSV 解析与摘要生成。

支持：xlsx, xls, csv
依赖：pandas, openpyxl（已在 requirements.txt 中）
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.services.file_processor.base import FileProcessor, ProcessResult

logger = logging.getLogger(__name__)


class DataProcessor(FileProcessor):
    """Excel / CSV 数据文件处理器。"""

    # 数据预览最大行数
    MAX_PREVIEW_ROWS = 5
    # 摘要中包含的最大列数描述
    MAX_COLUMNS_DESCRIBE = 20
    # 文本内容最大长度（防止超大文件撑爆上下文）
    MAX_TEXT_LENGTH = 3000

    def supported_types(self) -> list[str]:
        return ["excel", "csv"]

    async def process(self, file_path: str, mime_type: str) -> ProcessResult:
        """
        处理数据文件：
        1. 加载为 DataFrame
        2. 生成数据摘要（行列数、列名、数据类型、基础统计）
        3. 生成前 N 行预览
        """
        if not os.path.exists(file_path):
            return ProcessResult(success=False, error=f"文件不存在: {file_path}")

        try:
            import pandas as pd
        except ImportError:
            return ProcessResult(success=False, error="pandas 未安装")

        try:
            # 根据类型加载数据
            df = self._load_dataframe(file_path, mime_type)
            if df is None:
                return ProcessResult(success=False, error="无法解析文件内容")

            # 生成摘要
            summary = self._generate_summary(df)
            preview = self._generate_preview(df)
            statistics = self._generate_statistics(df)
            columns = list(df.columns)

            # 组装文本内容
            text_parts = [summary]
            if statistics:
                text_parts.append(f"数值列统计:\n{statistics}")
            if preview:
                text_parts.append(f"前{self.MAX_PREVIEW_ROWS}行数据:\n{preview}")

            text_content = "\n\n".join(text_parts)
            # 截断过长内容
            if len(text_content) > self.MAX_TEXT_LENGTH:
                text_content = text_content[:self.MAX_TEXT_LENGTH] + "\n...(内容已截断)"

            return ProcessResult(
                success=True,
                text_content=text_content,
                structured_data={
                    "summary": summary,
                    "columns": columns[:self.MAX_COLUMNS_DESCRIBE],
                    "preview": preview,
                    "row_count": len(df),
                    "column_count": len(df.columns),
                    "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
                },
                metadata={
                    "rows": len(df),
                    "columns": len(df.columns),
                    "column_names": columns,
                    "file_size": os.path.getsize(file_path),
                },
            )
        except Exception as e:
            logger.error(f"数据文件处理失败: {e}")
            return ProcessResult(success=False, error=f"解析失败: {str(e)}")

    def _load_dataframe(self, file_path: str, mime_type: str):
        """根据 MIME 类型加载 DataFrame。"""
        import pandas as pd

        ext = os.path.splitext(file_path)[1].lower()

        try:
            if ext == ".csv" or "csv" in mime_type:
                # 尝试多种编码
                for encoding in ["utf-8", "gbk", "gb2312", "latin-1"]:
                    try:
                        return pd.read_csv(file_path, encoding=encoding, nrows=10000)
                    except UnicodeDecodeError:
                        continue
                return pd.read_csv(file_path, encoding="utf-8", errors="ignore", nrows=10000)
            elif ext in (".xlsx", ".xls") or "spreadsheet" in mime_type or "excel" in mime_type:
                return pd.read_excel(file_path, nrows=10000)
            else:
                # 尝试作为 CSV
                return pd.read_csv(file_path, nrows=10000)
        except Exception as e:
            logger.warning(f"加载数据文件失败: {e}")
            return None

    def _generate_summary(self, df) -> str:
        """生成数据摘要。"""
        import pandas as pd

        lines = [
            f"数据集概况: {len(df)} 行 × {len(df.columns)} 列",
        ]

        # 列信息
        col_info = []
        for col in df.columns[:self.MAX_COLUMNS_DESCRIBE]:
            dtype = df[col].dtype
            null_count = df[col].isnull().sum()
            null_pct = f"({null_count}/{len(df)}空)" if null_count > 0 else ""
            col_info.append(f"  - {col} ({dtype}) {null_pct}")

        if col_info:
            lines.append("列信息:")
            lines.extend(col_info)

        if len(df.columns) > self.MAX_COLUMNS_DESCRIBE:
            lines.append(f"  ... 还有 {len(df.columns) - self.MAX_COLUMNS_DESCRIBE} 列未展示")

        return "\n".join(lines)

    def _generate_preview(self, df) -> str:
        """生成前 N 行数据预览。"""
        try:
            preview_df = df.head(self.MAX_PREVIEW_ROWS)
            return preview_df.to_string(index=False, max_colwidth=30)
        except Exception:
            return ""

    def _generate_statistics(self, df) -> str:
        """生成数值列的基础统计。"""
        import pandas as pd

        numeric_cols = df.select_dtypes(include=["number"])
        if numeric_cols.empty:
            return ""

        try:
            # 只取前 10 个数值列
            stats = numeric_cols.iloc[:, :10].describe().round(2)
            return stats.to_string()
        except Exception:
            return ""
