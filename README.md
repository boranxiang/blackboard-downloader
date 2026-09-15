# Blackboard Downloader

Automatically download course files from any **Blackboard Learn** instance. Supports any school, any term, and any file type.

## Features

- Works with any Blackboard Learn school (just enter your domain)
- Lists all your terms and lets you pick which one to download
- Pick exactly which modules to download (or use `--courses` to script it)
- Preserves top-level folder structure from Blackboard
- Skips files you've already downloaded
- Supports any file type: PDF, PPTX, DOCX, etc.
- Handles both classic attachments and Blackboard Ultra embedded files

## Requirements

- Python 3.8+
- Google Chrome installed

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/blackboard-downloader.git
cd blackboard-downloader

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

## Usage

### Interactive mode (recommended)

```bash
python3 bb_downloader.py
```

The script will ask for:

1. Your Blackboard domain (e.g. `learn.bu.edu`)
2. Which term to download
3. Which modules within that term (e.g. `1,3,5` or `1-3` or `all`)

By default, the script downloads every file type. Pass `--ext` to limit downloads to specific extensions.

### Command-line flags

```bash
python3 bb_downloader.py \
  --url learn.bu.edu \
  --output ~/Desktop/Blackboard \
  --ext .pdf .pptx .docx
```

| Flag | Description | Default |
|------|-------------|---------|
| `--url` | Blackboard domain | prompted |
| `--output` | Download folder | `~/Downloads/Blackboard` |
| `--ext` | File extensions | all extensions |
| `--courses` | Course names/IDs to download (substring match). Skips the interactive picker. | prompted |

### Output structure

```
Blackboard/
  MA225 Multivariate Calculus (Spring 26)/
    Lectures/
      lecture01.pdf
      lecture02.pdf
    Syllabus/
      syllabus.pdf
  LJ460 Haruki Murakami and His Sources (Spring 26)/
    Content/
      reading01.pdf
      ...
```

## How it works

1. Opens a Chrome window for you to log in manually (handles SSO/2FA)
2. Transfers the session cookies to a `requests` session
3. Uses the Blackboard REST API to enumerate your courses and content
4. Parses both traditional attachments and Blackboard Ultra's `data-bbfile` embedded links
5. Downloads matching files into a mirrored folder structure

## Notes

- **Re-running is safe** — already downloaded files are skipped
- **External links are not downloaded** (e.g. files hosted on Google Drive or OneDrive)
- Tested on Blackboard Learn SaaS (Ultra experience) at Boston University (learn.bu.edu) and Trinity College Dublin (tcd.blackboard.com)

## Contributing

PRs welcome. If your school's Blackboard uses a different content structure and some files aren't being picked up, open an issue with the output of the debug steps in the wiki.

## License

MIT
