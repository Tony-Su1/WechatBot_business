# WeChatbot Customer Assistant

A Windows-based WeChat AI automation bot extended from
[WeChatBot_WXAUTO_SE](https://github.com/iwyxdxl/WeChatBot_WXAUTO_SE).
It improves compatibility with newer OpenAI GPT APIs, supports hot-reloadable
prompts, and adds private-chat customer profile memory for client follow-up
workflows.

This project is intended for personal learning, LLM application experiments,
WeChat automation research, and private-domain customer assistant experiments.

## Project Overview

The upstream project provides local WeChat automation, a Web UI, private and
group chat replies, prompt-based personas, memory, reminders, and LLM-powered
responses. This version focuses the bot toward private-chat customer work:

1. Improved compatibility with newer OpenAI GPT APIs, including GPT-5 models.
2. Hot-reloadable prompts for faster persona and prompt iteration.
3. Private-chat customer profile memory for key dates, preferences, sales stage,
   follow-up progress, and human handoff hints.

The goal is to preserve the original bot architecture while making it more
useful as a lightweight customer follow-up assistant.

## Main Features

### WeChat AI Auto Reply

- Monitors PC WeChat messages automatically.
- Supports private chats and group chats.
- Supports group mention and keyword triggers.
- Assigns different prompts and personas to different users or groups.
- Preserves multi-turn conversation and memory behavior from the upstream project.

### Private Customer Profile Memory

- Keeps base role prompts in `prompts/`.
- Stores structured customer data in `data/customer_assistant.db`.
- Writes each private-chat customer's prompt-ready summary cache to
  `CustomerMemory/`.
- Injects the customer's profile into the system prompt before each reply.
- After each normal private-chat reply, extracts structured customer updates
  into SQLite and refreshes the Markdown cache.
- Tracks key dates, preferences, personality notes, current sales stage,
  follow-up progress, and human handoff reasons.

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

## Project Structure

```text
WeChatbot Customer Assistant/
|-- bot.py                     # Main bot runtime
|-- config.py                  # Main configuration
|-- config_editor.py           # Web UI configuration editor
|-- Run.bat                    # Windows startup script
|-- requirements.txt           # Python dependencies
|-- .env.example               # Environment variable names
|-- prompts/                   # Prompt/persona examples
|-- CustomerMemory/            # Prompt-ready profile cache, ignored by Git
|-- data/                      # SQLite customer DB, ignored by Git
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

### 1. Install dependencies

```bat
python -m pip install -r requirements.txt
```

The original Windows package can also use:

```bat
Run.bat
```

### 2. Configure the API key

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

### 3. Configure users and prompts

Edit `LISTEN_LIST` in `config.py`:

```python
LISTEN_LIST = [
    ['Friend nickname', 'example'],
]
```

Create your own prompt from `prompts/example.md`. Personal prompts, customer
databases, customer profile caches, memories, chat contexts, downloads, and API
keys are ignored by Git.

### 4. Start the bot

1. Open and sign in to PC WeChat.
2. Keep WeChat running.
3. Run `Run.bat` or `python config_editor.py`.
4. Open the local Web UI, review the configuration, and start the bot.

## Configuration Checklist

- API key is configured and valid.
- Model name matches the selected provider.
- Base URL matches the provider.
- WeChat nicknames are exact.
- Every target is mapped to an existing prompt file.
- PC WeChat is signed in and using a compatible version.
- Customer profile memory is enabled only where you intend the bot to retain
  customer follow-up information.

## Use Cases

- Private-domain customer follow-up experiments.
- WeChat auto-reply testing.
- Prompt engineering and persona design.
- OpenAI API integration practice.
- Local automation workflow research.
- Resume and portfolio demonstration.

## Future Improvements

- Cleaner modular plugin architecture.
- RAG-based insurance product and compliance knowledge retrieval.
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
- Privacy, consent, and data-protection obligations for customer information.

Do not use this project for spam, harassment, illegal automation, public
platform abuse, unauthorized access, or unauthorized personal-data processing.
The developer is not responsible for misuse, account restrictions, third-party
API output, or other consequences caused by users.

## Credits

- [iwyxdxl/WeChatBot_WXAUTO_SE](https://github.com/iwyxdxl/WeChatBot_WXAUTO_SE)
- [KouriChat/KouriChat](https://github.com/KouriChat/KouriChat)

Thanks to the original developers and open-source contributors.

## License

This project follows the license requirements of the upstream project and its
dependencies. See:

- [LICENSE](LICENSE)
- [LICENSE_COMPLIANCE.md](LICENSE_COMPLIANCE.md)
- [DEPENDENCIES.txt](DEPENDENCIES.txt)

Review the license requirements of WeChatBot_WXAUTO_SE and KouriChat before
redistribution.

## Resume Summary

> Modified and extended an open-source Windows WeChat automation bot by
> improving OpenAI GPT API compatibility, adding hot-reloadable prompt
> management, and adding private-chat customer profile memory for client
> follow-up workflows.
