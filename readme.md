# WeChatbot_withjm

A Windows-based WeChat AI automation bot extended from
[WeChatBot_WXAUTO_SE](https://github.com/iwyxdxl/WeChatBot_WXAUTO_SE).
It improves compatibility with newer OpenAI GPT APIs, supports hot-reloadable
prompts, and integrates a JM download service based on
[JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python).

This project is intended for personal learning, LLM application experiments,
WeChat automation research, and portfolio demonstration.

## Project Overview

The upstream project provides local WeChat automation, a Web UI, private and
group chat replies, prompt-based personas, memory, reminders, and LLM-powered
responses. This repository extends it in three main directions:

1. Improved compatibility with newer OpenAI GPT APIs, including GPT-5 models.
2. Hot-reloadable prompts for faster persona and prompt iteration.
3. A custom `jm_download_service.py` module for message-triggered PDF tasks.

The goal is to preserve the original bot architecture while turning it into a
more flexible AI assistant and local task-automation entry point.

## Main Features

### WeChat AI Auto Reply

- Monitors PC WeChat messages automatically.
- Supports private chats and group chats.
- Supports group mention and keyword triggers.
- Assigns different prompts and personas to different users or groups.
- Preserves multi-turn conversation and memory behavior from the upstream project.

### Improved OpenAI API Compatibility

- Supports OpenAI and OpenAI-compatible API endpoints.
- Handles GPT-5 token parameter differences.
- Improves model-switching stability.
- Keeps the integration ready for newer compatible model providers.

### Hot-Reloadable Prompts

- Updates prompt rules without fully restarting the bot.
- Speeds up persona testing and prompt engineering.
- Supports long-running assistant scenarios.
- Provides a foundation for multi-persona prompt management.

### JM Download Service

The custom `jm_download_service.py` module uses
[JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python)
to download an album, generate a PDF, and return it through WeChat.

Trigger formats:

```text
Group chat: @BotName jm123456
Private chat: jm123456
```

The command is matched strictly. Extra text does not trigger a download.

> This feature is for personal learning and local experimentation. Users are
> responsible for complying with local laws, age requirements, platform rules,
> and copyright restrictions.

### Web UI Configuration

- Local browser-based configuration interface.
- User and group management.
- Prompt and persona management.
- Runtime logs and bot controls.

### Additional Message Features

- Text, image, emoji, voice transcription, and link handling.
- Emotional-style replies and optional emoji sending.
- Message merging and simulated reply delays.
- Reminders, memory summaries, and scheduled tasks.

## Changes from the Upstream Project

| Module | Upstream | This repository |
| --- | --- | --- |
| WeChat automation | Supported | Preserved |
| Private/group replies | Supported | Preserved and stabilized |
| Web UI | Supported | Preserved |
| OpenAI API calls | Partial newer-model support | Improved GPT-5 compatibility |
| Prompt updates | Usually require restart | Hot-reload support |
| External task services | Not included | JM download/PDF service |
| Project direction | AI chatbot | AI chat and task automation |

## Tech Stack

- Python
- Windows UI automation
- PC WeChat
- OpenAI-compatible APIs
- Flask Web UI
- Prompt and persona management
- External Python service integration

## Project Structure

```text
WeChatbot_withjm/
|-- bot.py                     # Main bot runtime
|-- config.py                  # Main configuration
|-- config_editor.py           # Web UI configuration editor
|-- jm_download_service.py     # JM download and PDF service
|-- Run.bat                    # Windows startup script
|-- requirements.txt           # Python dependencies
|-- .env.example               # Environment variable names
|-- prompts/                   # Prompt/persona examples
|-- emojis/                    # Emoji resources
|-- templates/                 # Web UI templates
|-- Demo_Image/                # Demo images
|-- CHANGELOG.md
|-- DEPENDENCIES.txt
|-- LICENSE
`-- README.md
```

## Requirements

Recommended environment:

- Windows 11
- Python 3.9-3.12
- PC WeChat 4.1.2 matching the bundled automation library
- `pip`
- A valid OpenAI or OpenAI-compatible API key

The bundled `wxautox4_wechatbot` wheel is not committed to this repository.
You must provide a compatible authorized wheel or replace it with a compatible
automation implementation.

## Quick Start

### 1. Clone the repository

```bat
git clone https://github.com/Tony-Su1/WeChatbot_withjm.git
cd WeChatbot_withjm
```

### 2. Install dependencies

```bat
python -m pip install -r requirements.txt
```

The original Windows package can also use:

```bat
Run.bat
```

### 3. Configure the API key

`config.py` reads the OpenAI API key from the Windows environment:

```bat
setx OPENAI_API_KEY "your_api_key_here"
```

Close and reopen the terminal after running `setx`. Do not commit real API
keys to Git.

Optional Web UI password:

```bat
setx WECHATBOT_LOGIN_PASSWORD "your_password"
```

### 4. Configure users and prompts

Edit `LISTEN_LIST` in `config.py`:

```python
LISTEN_LIST = [
    ['Friend nickname', 'example'],
    ['Group name', 'example'],
]
```

Create your own prompt from `prompts/example.md`. Personal prompts, memories,
chat contexts, downloads, and API keys are ignored by Git.

### 5. Start the bot

1. Open and sign in to PC WeChat.
2. Keep WeChat running.
3. Run `Run.bat` or `python config_editor.py`.
4. Open the local Web UI, review the configuration, and start the bot.

## Configuration Checklist

- API key is configured and valid.
- Model name matches the selected provider.
- Base URL matches the provider.
- WeChat nicknames and group names are exact.
- Every target is mapped to an existing prompt file.
- PC WeChat is signed in and using a compatible version.
- JM downloads comply with applicable laws and platform rules.

## Use Cases

- Personal AI assistant experiments.
- WeChat auto-reply testing.
- OpenAI API integration practice.
- Prompt engineering and persona design.
- Local automation workflow research.
- External Python service integration.
- Resume and portfolio demonstration.

## Future Improvements

- Cleaner modular plugin architecture.
- RAG-based local knowledge retrieval.
- Broader model-provider compatibility.
- Persistent rotating log files.
- Safer configuration management.
- Unit and integration tests.
- Better task queue, cooldown, and timeout controls.

## Disclaimer

This project is provided for technical research, personal learning, and local
experimentation. Users must comply with:

- Applicable laws and regulations.
- WeChat platform rules.
- API provider terms of service.
- Copyright and content-usage requirements.
- Licenses and restrictions of all third-party projects.

Do not use this project for spam, harassment, illegal automation, public
platform abuse, unauthorized access, or copyright infringement. The developer
is not responsible for misuse, account restrictions, third-party API output,
or other consequences caused by users.

## Credits

- [iwyxdxl/WeChatBot_WXAUTO_SE](https://github.com/iwyxdxl/WeChatBot_WXAUTO_SE)
- [KouriChat/KouriChat](https://github.com/KouriChat/KouriChat)
- [hect0x7/JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python)

Thanks to the original developers and open-source contributors.

## License

This project follows the license requirements of the upstream project and its
dependencies. See:

- [LICENSE](LICENSE)
- [LICENSE_COMPLIANCE.md](LICENSE_COMPLIANCE.md)
- [DEPENDENCIES.txt](DEPENDENCIES.txt)

Review the license requirements of WeChatBot_WXAUTO_SE, KouriChat, and
JMComic-Crawler-Python before redistribution.

## Resume Summary

> Modified and extended an open-source Windows WeChat automation bot by
> improving OpenAI GPT API compatibility, adding hot-reloadable prompt
> management, and integrating a custom JM download/PDF service based on an
> external Python crawler library.
