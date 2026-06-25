# Antigravity Sync

A cross-platform synchronization daemon and graphical interface for **Antigravity** (the agentic coding assistant). It automates backing up and restoring your local active chats, configuration settings, custom skills, and plugins via **GitHub** and/or **Google Drive**.

## Features

- 🖥️ **Cross-Platform GUI**: Built with Tkinter featuring a modern dark-theme dashboard.
- 🟢 **Automated Task Completion Detection**: Monitors filesystem updates in your active conversations. When Antigravity goes idle, a sync is automatically triggered after a configurable cooldown.
- 📦 **Dual Backend Support**: Sychronize using GitHub repositories, local Google Drive desktop clients, or both.
- 🚀 **Autostart & Search Integration**:
  - **Windows**: Startup folder integration (`.bat` background launch via `pythonw.exe`), desktop and Start Menu search index integration (`.lnk`).
  - **macOS**: LaunchAgent configuration (`.plist`) and `.app` bundle under `~/Applications` ( Spotlight indexed).
  - **Linux**: Autostart desktop entry (`.desktop`) and Applications search menu indexing.
- 🔒 **Security First**: Automatically ignores sensitive files like `oauth_creds.json` and `installation_id`.

## Installation

1. Clone or download this repository on your machine.
2. Run the installer wizard:
   ```bash
   python install.py
   ```
   *Note: This will install required helper packages (`pystray`, `Pillow`) and configure system launchers and autostart.*

## Usage

- Launch **Antigravity Sync** from your Desktop shortcut or search menu.
- Configure your preferred backend (Git Remote or local Google Drive Path).
- Save and hit **Force Backup Sync** to upload your current state or **Force Restore Chats** to sync down history.
- The app will run quietly in your system tray/menu bar.
