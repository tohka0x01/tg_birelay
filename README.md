# TGBiRelay · Telegram 双向客服中继

TGBiRelay（Telegram Bidirectional Relay）是一套自托管的多 Bot 转发系统，适合客服、工单、社群等场景：

- **多 Bot 托管**：一个主控 Bot 统一调度，任意数量子 Bot 并行工作；
- **双向转发**：支持私聊直连与 Topic 论坛两种模式，自动维护会话映射；
- **验证码/黑名单**：内置挑战题库，可自定义题型、开关、拉黑/解封指令；
- **自定义欢迎语**：管理员欢迎语、客户欢迎语均可配置；
- **轻量依赖**：仅依赖 `python-telegram-bot==20.7` 与 `python-dotenv`，使用 SQLite 持久化。

---

## 目录结构

```
tg_birelay/
├── README.md          # 项目说明（本文件）
├── install.sh         # 安装 / 升级 / 卸载脚本
└── tg_birelay/
    ├── __init__.py
    ├── app.py         # 主程序
    ├── database.py    # SQLite 封装
    └── captcha.py     # 验证码模块
```

---

## 一键安装

```bash
bash <(curl -Ls https://raw.githubusercontent.com/tohka0x01/tg_birelay/refs/heads/master/install.sh)
```

安装脚本会：

1. 安装 `curl / python3 / python3-venv / python3-pip` 等依赖；  
2. 将代码拉取至 `/opt/tg_birelay`（可通过 `APP_DIR` 覆盖）；  
3. 创建或更新虚拟环境并安装依赖；  
4. 交互式写入 `.env`：包括主控 Bot Token 与 **唯一 Owner 数字 ID**，可选日志频道；  
5. 生成 systemd 服务 `tgbirelay` 并启动。

再次执行“安装/更新”会覆盖代码与 `.env`（数据库 `tg_hosts.db` 保留）。卸载可在菜单中选择 `2`，脚本会停止服务并删除安装目录。

> 若需使用自己的代码分支，可在执行前设置 `REPO_BASE` 指向新的 raw 地址。

---

## 手动部署 / 调试

1. 安装依赖
   ```bash
   pip install python-telegram-bot==20.7 python-dotenv
   ```
2. 新建 `.env`
   ```env
   MANAGER_TOKEN=你的主控 Bot Token
   MANAGER_OWNER_ID=123456789     # 仅允许该账号访问主控面板
   # ADMIN_CHANNEL=-1001234567890 # 可选，如需推送日志
   DATABASE_PATH=./tg_hosts.db    # 可选，默认放在当前目录
   ```
3. 启动
   ```bash
   PYTHONPATH=$(pwd) python -m tg_birelay.app
   ```
4. 在 Telegram 与主控 Bot 对话，根据菜单提示添加子 Bot、选择模式、设置验证码与欢迎语等。

---

## FAQ

- **如何限制只有我能使用面板？**  
  安装时填写 `MANAGER_OWNER_ID`，运行期所有主控命令都会校验该 ID，其他人无法打开菜单。

- **更新会不会丢数据？**  
  代码与 `.env` 会被覆盖，SQLite 数据库 `tg_hosts.db` 不会删除；如需保留旧 `.env` 可提前备份。

- **如何查看运行日志？**  
  `journalctl -u tgbirelay -f` 可实时查看；若设置 `ADMIN_CHANNEL`，系统也会把关键事件推送到频道/群。

欢迎 Fork / 提交 PR，祝使用顺利！
