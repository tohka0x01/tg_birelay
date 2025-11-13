# TGBiRelay - TG 双向机器人中枢

TGBiRelay（Telegram Bidirectional Relay）专为 TG 双向客服/托管场景打造，单实例即可承载多枚 Bot，实现“用户 ↔ 管理员”的安全双向路由。

- ✅ SQLite 持久化：多 Bot 配置、黑名单、消息映射与 Topic 绑定统一存储，备份与迁移轻松。
- ✅ 模块化逻辑：验证码、Topic 路由、私聊路由、命令面板分层实现，易于扩展维护。
- ✅ 欢迎语可配置：管理员面板欢迎语、成员 Bot `/start` 欢迎语均可在 Telegram 中交互配置。
- ✅ 交互友好：在chat中交互式设置。
- ✅ 精简依赖：仅依赖 `python-telegram-bot==20.7` 与 `python-dotenv`，保留 webhook/多进程扩展空间。

## 目录结构

```
tg_birelay/
├── README.md          # 使用说明
├── install.sh         # 一键安装/卸载脚本
└── tg_birelay/        # Python 包
    ├── __init__.py
    ├── app.py         # 主进程 + Bot 逻辑
    ├── database.py    # SQLite 封装 + 数据访问
    └── captcha.py     # 验证码模块
```

## 一键安装脚本


```bash
bash <(curl -Ls https://raw.githubusercontent.com/tohka0x01/tg_birelay/main/install.sh)
```

脚本会：

1. 安装 `curl / python3 / python3-venv / python3-pip` 等依赖；
2. 将 `tg_birelay` 目录下载至 `/opt/tg_birelay`（可通过 `APP_DIR` 覆盖）；
3. 创建虚拟环境并安装运行依赖；
4. 交互式写入 `.env`（仅需管理 Bot Token，可选日志频道 ID）；
5. 注册 systemd 服务并立即启动。

卸载同样通过脚本菜单完成，自动停止服务并移除目录。

> 需要替换下载源时，可在执行前设置 `REPO_BASE` 指向新的 raw 目录。

## 手动运行（开发/调试）

1. 安装依赖
   ```bash
   pip install python-telegram-bot==20.7 python-dotenv
   ```
2. 在代码根目录创建 .env
   ```env
   MANAGER_TOKEN=你的管理 Bot Token
   ADMIN_CHANNEL=选填日志频道/群 ID
   DATABASE_PATH=./tg_hosts.db   # 可选，默认为本地
   ```
3. 启动程序
   ```bash
   cd /opt/tg_birelay && python -m tg_birelay.app
   # 如果人在 tg_birelay 子目录中, 请手动添加 PYTHONPATH
   # PYTHONPATH=$(pwd)/.. python -m tg_birelay.app
   ```
4. 打开管理 Bot，按提示传入 Bot Token、Topic ID 等数据, 完成配置后可直接进行 TG ˫向交互测试。
