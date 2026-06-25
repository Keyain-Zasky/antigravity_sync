import os
import sys
import platform
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

class SyncInstaller:
    def __init__(self, headless=False):
        self.headless = headless
        self.script_dir = Path(__file__).resolve().parent
        self.target_script = self.script_dir / "sync_gui.py"
        self.os_type = platform.system().lower()
        
        if not self.headless:
            self.setup_gui()
        else:
            self.run_install()

    def run_install(self):
        print(f"Detected OS: {self.os_type.capitalize()}")
        
        # 1. Install Dependencies
        self.install_dependencies()
        
        # 2. Configure Autostart
        self.setup_autostart()
        
        # 3. Create desktop/start menu shortcuts
        self.create_shortcuts()
        
        print("Installation completed successfully!")

    def install_dependencies(self):
        print("Installing required Python packages (pystray, Pillow)...")
        try:
            # run pip install
            subprocess.run([sys.executable, "-m", "pip", "install", "pystray", "Pillow"], check=True)
            print("Dependencies installed successfully.")
        except Exception as e:
            msg = f"Could not install dependencies automatically via pip: {e}."
            print(msg)
            if not self.headless:
                messagebox.showwarning("Warning", f"{msg}\nThe system tray icon might not be available.")

    def setup_autostart(self):
        print("Configuring Autostart...")
        
        # We want to run sync_gui.py with pythonw (no terminal) on Windows, or python with --headless/tray
        python_executable = sys.executable
        # Use pythonw on Windows to prevent terminal window
        if self.os_type == "windows":
            python_w = Path(python_executable).parent / "pythonw.exe"
            if python_w.exists():
                python_executable = str(python_w)

        cmd = f'"{python_executable}" "{self.target_script}"'

        try:
            if self.os_type == "windows":
                startup_folder = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
                startup_file = startup_folder / "AntigravitySync.bat"
                with open(startup_file, "w", encoding="utf-8") as f:
                    f.write(f'@echo off\nstart "" {cmd}\n')
                print(f"Created startup batch file: {startup_file}")
                
            elif self.os_type == "darwin": # macOS
                launch_agents = Path.home() / "Library" / "LaunchAgents"
                launch_agents.mkdir(parents=True, exist_ok=True)
                plist_path = launch_agents / "com.antigravity.sync.plist"
                
                plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.antigravity.sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_executable}</string>
        <string>{self.target_script}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
                with open(plist_path, "w", encoding="utf-8") as f:
                    f.write(plist_content)
                print(f"Created macOS LaunchAgent plist: {plist_path}")
                
            elif self.os_type == "linux":
                autostart_folder = Path.home() / ".config" / "autostart"
                autostart_folder.mkdir(parents=True, exist_ok=True)
                desktop_file = autostart_folder / "antigravity-sync.desktop"
                
                desktop_content = f"""[Desktop Entry]
Type=Application
Exec={python_executable} {self.target_script}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=Antigravity Sync
Comment=Backup and synchronization daemon for Antigravity
"""
                with open(desktop_file, "w", encoding="utf-8") as f:
                    f.write(desktop_content)
                print(f"Created Linux Autostart entry: {desktop_file}")
                
        except Exception as e:
            print(f"Failed to setup autostart: {e}")

    def create_windows_lnk(self, shortcut_path, target_path, arguments="", working_dir="", icon_path=""):
        """Helper to create a native Windows .lnk shortcut using PowerShell, falling back to VBScript or a BAT file."""
        ps_command = (
            f"$WshShell = New-Object -ComObject WScript.Shell; "
            f"$Shortcut = $WshShell.CreateShortcut('{shortcut_path}'); "
            f"$Shortcut.TargetPath = '{target_path}'; "
            f"$Shortcut.Arguments = '{arguments}'; "
            f"$Shortcut.WorkingDirectory = '{working_dir}'; "
        )
        if icon_path:
            ps_command += f"$Shortcut.IconLocation = '{icon_path}'; "
        ps_command += "$Shortcut.Save()"

        try:
            # Try via PowerShell first (highly reliable on modern Windows)
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_command], capture_output=True, text=True)
            if res.returncode == 0:
                return
        except Exception:
            pass

        # Try via legacy VBScript as second choice
        try:
            import tempfile
            vbs_path = Path(tempfile.gettempdir()) / "create_lnk.vbs"
            vbs_content = (
                f'Set oWS = WScript.CreateObject("WScript.Shell")\n'
                f'sLinkFile = "{shortcut_path}"\n'
                f'Set oLink = oWS.CreateShortcut(sLinkFile)\n'
                f'oLink.TargetPath = "{target_path}"\n'
                f'oLink.Arguments = "{arguments}"\n'
                f'oLink.WorkingDirectory = "{working_dir}"\n'
            )
            if icon_path:
                vbs_content += f'oLink.IconLocation = "{icon_path}"\n'
            vbs_content += 'oLink.Save()\n'
            
            with open(vbs_path, "w", encoding="utf-8") as f:
                f.write(vbs_content)
            subprocess.run(["cscript", "/nologo", str(vbs_path)], capture_output=True)
            vbs_path.unlink()
            return
        except Exception:
            pass

        # Fallback to simple batch file if COM objects/PowerShell are completely blocked by Group Policy
        try:
            bat_path = Path(shortcut_path).with_suffix(".bat")
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(f'@echo off\nstart "" "{target_path}" {arguments}\n')
            print(f"Group Policy block detected. Fallback batch shortcut created: {bat_path}")
        except Exception as e:
            print(f"Failed to create windows shortcut: {e}")

    def create_shortcuts(self):
        print("Creating desktop and search menu shortcuts...")
        try:
            desktop = Path.home() / "Desktop"
            python_w = Path(sys.executable).parent / "pythonw.exe"
            exec_cmd = python_w if python_w.exists() else sys.executable

            if self.os_type == "windows":
                # Resolve OneDrive/custom desktop path using registry
                try:
                    import winreg
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
                    val, _ = winreg.QueryValueEx(key, "Desktop")
                    winreg.CloseKey(key)
                    desktop = Path(os.path.expandvars(val))
                except Exception:
                    pass
                
                # Convert PNG to ICO for Windows shortcuts natively
                icon_png = self.script_dir / "icon.png"
                icon_ico = self.script_dir / "icon.ico"
                if icon_png.exists():
                    try:
                        from PIL import Image
                        img = Image.open(icon_png)
                        img.save(icon_ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
                        print("Converted icon.png to icon.ico for native shortcuts.")
                    except Exception as e:
                        print(f"Failed to convert PNG to ICO: {e}")
                
                icon_path_arg = str(icon_ico) if icon_ico.exists() else ""

                # 1. Desktop LNK Shortcut (clean, no console window)
                desktop_lnk = desktop / "Antigravity Sync.lnk"
                self.create_windows_lnk(desktop_lnk, exec_cmd, f'"{self.target_script}"', str(self.script_dir), icon_path_arg)
                print(f"Windows desktop shortcut created: {desktop_lnk}")

                # 2. Start Menu Shortcut (Makes it searchable in Windows Search Bar!)
                start_menu_folder = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                start_menu_lnk = start_menu_folder / "Antigravity Sync.lnk"
                self.create_windows_lnk(start_menu_lnk, exec_cmd, f'"{self.target_script}"', str(self.script_dir), icon_path_arg)
                print(f"Windows Start Menu shortcut created (search indexed): {start_menu_lnk}")
                
            elif self.os_type == "darwin": # macOS Spotlight search integration
                # 1. Desktop Launcher
                desktop_launcher = desktop / "Antigravity Sync"
                with open(desktop_launcher, "w", encoding="utf-8") as f:
                    f.write(f'#!/bin/bash\n"{sys.executable}" "{self.target_script}" &\n')
                desktop_launcher.chmod(0o755)
                
                # 2. Applications app bundle wrapper (indexed by Spotlight)
                app_dir = Path.home() / "Applications" / "Antigravity Sync.app"
                macos_dir = app_dir / "Contents" / "MacOS"
                macos_dir.mkdir(parents=True, exist_ok=True)
                
                app_launcher = macos_dir / "Antigravity Sync"
                with open(app_launcher, "w", encoding="utf-8") as f:
                    f.write(f'#!/bin/bash\nexec "{sys.executable}" "{self.target_script}"\n')
                app_launcher.chmod(0o755)
                
                # Info.plist
                plist = app_dir / "Contents" / "Info.plist"
                plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>Antigravity Sync</string>
    <key>CFBundleIdentifier</key>
    <string>com.antigravity.sync</string>
    <key>CFBundleName</key>
    <string>Antigravity Sync</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
</dict>
</plist>
"""
                with open(plist, "w", encoding="utf-8") as f:
                    f.write(plist_content)
                print(f"macOS applications bundle (.app) registered: {app_dir}")

            elif self.os_type == "linux":
                # 1. Desktop Launcher
                desktop_launcher = desktop / "Antigravity Sync"
                with open(desktop_launcher, "w", encoding="utf-8") as f:
                    f.write(f'#!/bin/bash\n"{sys.executable}" "{self.target_script}" &\n')
                desktop_launcher.chmod(0o755)

                # 2. Applications Menu Entry (.desktop) for search indexer
                apps_folder = Path.home() / ".local" / "share" / "applications"
                apps_folder.mkdir(parents=True, exist_ok=True)
                desktop_file = apps_folder / "antigravity-sync.desktop"
                
                desktop_content = f"""[Desktop Entry]
Type=Application
Exec="{sys.executable}" "{self.target_script}"
Hidden=false
NoDisplay=false
Name=Antigravity Sync
Comment=Backup and synchronization tool for Antigravity
Icon=system-run
Terminal=false
Categories=Utility;Settings;
"""
                with open(desktop_file, "w", encoding="utf-8") as f:
                    f.write(desktop_content)
                print(f"Linux applications menu entry registered: {desktop_file}")

        except Exception as e:
            print(f"Could not create shortcuts: {e}")

    def setup_gui(self):
        self.root = tk.Tk()
        self.root.title("Antigravity Sync Installer")
        self.root.geometry("450x300")
        self.root.resizable(False, False)
        
        style = ttk.Style()
        style.theme_use("clam")
        
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        title_label = ttk.Label(main_frame, text="Antigravity Sync Setup Wizard", font=("Segoe UI", 14, "bold"))
        title_label.pack(pady=(0, 10))
        
        desc = (
            f"This installer will configure Antigravity Sync on your system.\n\n"
            f"Detected Platform: {self.os_type.capitalize()}\n"
            f"Installation Path: {self.script_dir}\n"
        )
        desc_label = ttk.Label(main_frame, text=desc, justify=tk.LEFT, font=("Segoe UI", 10))
        desc_label.pack(fill=tk.X, pady=(0, 20))
        
        self.progress_var = tk.StringVar(value="Ready to install.")
        self.progress_label = ttk.Label(main_frame, textvariable=self.progress_var, font=("Segoe UI", 9, "italic"))
        self.progress_label.pack(fill=tk.X, pady=(0, 10))
        
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.install_btn = ttk.Button(btn_frame, text="Install Now", command=self.gui_install)
        self.install_btn.pack(side=tk.RIGHT, padx=5)
        
        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self.root.destroy)
        cancel_btn.pack(side=tk.RIGHT, padx=5)
        
        self.root.mainloop()

    def gui_install(self):
        self.install_btn.config(state="disabled")
        self.progress_var.set("Installing dependencies...")
        self.root.update()
        
        self.install_dependencies()
        
        self.progress_var.set("Configuring autostart...")
        self.root.update()
        self.setup_autostart()
        
        self.progress_var.set("Creating desktop shortcuts...")
        self.root.update()
        self.create_shortcuts()
        
        self.progress_var.set("Installation complete!")
        messagebox.showinfo("Success", "Antigravity Sync has been successfully installed and configured to run on startup!")
        self.root.destroy()

if __name__ == "__main__":
    headless = "--headless" in sys.argv
    installer = SyncInstaller(headless=headless)
