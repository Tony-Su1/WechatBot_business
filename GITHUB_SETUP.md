# GitHub 版本使用说明

此仓库不会包含 API Key、聊天记录、核心记忆、下载内容、私人 Prompt、
Windows 安装程序或项目附带的私有 wheel。

## 开始使用

1. 安装 Python 3.9-3.12 和微信客户端。
2. 安装 `requirements.txt` 中的依赖。
3. 在 Windows 中设置 API Key：

   ```bat
   setx OPENAI_API_KEY "你的 API Key"
   ```

4. 修改 `config.py` 中的 `LISTEN_LIST`、模型和其他开关。
5. 从 `prompts/example.md` 创建自己的角色 Prompt。
6. 运行 `Run.bat`。

## JM 下载

- 群聊：`@机器人 jm123456`
- 私聊：`jm123456`

请确保下载和传播内容符合所在地法律、年龄要求及版权规定。

## 安全提醒

不要把真实 API Key、聊天记录、记忆文件或私人 Prompt 提交到 Git。
