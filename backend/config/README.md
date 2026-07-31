# 配置分层说明

本目录存放各环境的配置模板，**不存放真实密钥**。

## 文件说明

| 文件 | 用途 |
|------|------|
| `development.env` | 本地开发配置（可直接使用） |
| `production.env` | 生产环境模板（需替换 CHANGE_ME） |

## 使用方式

```bash
# 本地开发：直接复制开发配置
cp config/development.env .env

# 生产部署：复制生产模板并填入真实值
cp config/production.env .env
vim .env  # 替换所有 CHANGE_ME
```

## 配置优先级

环境变量 > `.env` 文件 > `config.py` 中的默认值

docker-compose 中通过 `environment:` 字段覆盖的变量优先于 `env_file` 中的值。

## 安全提醒

- `.env` 文件已在 `.gitignore` 中，不会被提交
- 生产密钥建议通过 KMS/Vault 注入，不写入文件
- `CHANGE_ME` 占位符必须在部署前全部替换
