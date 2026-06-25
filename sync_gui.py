import os
import sys
import time
import json
import shutil
import platform
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Optional dependencies for system tray
try:
    from PIL import Image, ImageDraw, ImageTk
    import pystray
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

# Default Config
DEFAULT_CONFIG = {
    "sync_backend": "github",
    "cooldown_seconds": 30,
    "git_remote": "origin",
    "google_drive_path": "",
    "exclude_patterns": ["oauth_creds.json", "installation_id", "tmp/", ".git/"]
}

class AntigravitySyncApp:
    def __init__(self, headless=False):
        self.headless = headless
        self.script_dir = Path(__file__).resolve().parent
        self.config_path = self.script_dir / "sync_config.json"
        self.backup_dir = self.script_dir / "backup_data"
        self.backup_dir.mkdir(exist_ok=True)
        
        # Prevent Windows taskbar from grouping python app with python.exe default icon
        if platform.system().lower() == "windows":
            try:
                import ctypes
                myappid = "com.antigravity.sync.daemon.v1"
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception:
                pass

        self.status = "Idle"
        self.last_sync_time = "Never"
        self.is_monitoring = True
        self.log_messages = []
        
        self.load_config()
        self.detect_gemini_path()
        
        # Daemon state variables
        self.last_mtime = 0.0
        self.active_cooldown_start = None
        
        # Start Daemon Thread
        self.daemon_thread = threading.Thread(target=self.run_daemon, daemon=True)
        self.daemon_thread.start()
        
        if not self.headless:
            self.setup_gui()
            if TRAY_AVAILABLE:
                self.setup_tray()
        else:
            self.log("Running in headless mode.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.log("Shutting down sync daemon...")

    def detect_gemini_path(self):
        home = Path.home()
        self.gemini_path = home / ".gemini"
        if not self.gemini_path.exists():
            self.log(f"Warning: .gemini directory not found at default location: {self.gemini_path}")
        else:
            self.log(f"Detected .gemini directory: {self.gemini_path}")

    def load_config(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                # Fill missing keys
                for k, v in DEFAULT_CONFIG.items():
                    if k not in self.config:
                        self.config[k] = v
            except Exception as e:
                self.log(f"Error loading config: {e}. Using defaults.")
                self.config = DEFAULT_CONFIG.copy()
        else:
            self.config = DEFAULT_CONFIG.copy()
            self.save_config()

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            self.log("Configuration saved successfully.")
        except Exception as e:
            self.log(f"Error saving config: {e}")

    def log(self, message):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        msg = f"[{timestamp}] {message}"
        print(msg)
        self.log_messages.append(msg)
        if len(self.log_messages) > 200:
            self.log_messages.pop(0)
        
        # Update GUI if running
        if not self.headless and hasattr(self, "log_text"):
            try:
                self.log_text.config(state="normal")
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
                self.log_text.config(state="disabled")
            except Exception:
                pass

    def get_max_mtime(self):
        """Recursively checks modification times in .gemini directory, excluding temporary files."""
        if not self.gemini_path.exists():
            return 0.0
        
        max_time = 0.0
        try:
            for root, dirs, files in os.walk(self.gemini_path):
                # Filter out excluded directories
                dirs[:] = [d for d in dirs if not any(exp in os.path.join(root, d) for exp in self.config["exclude_patterns"])]
                
                for file in files:
                    file_path = Path(root) / file
                    # Skip excluded files
                    if any(exp in str(file_path) for exp in self.config["exclude_patterns"]):
                        continue
                    try:
                        mtime = file_path.stat().st_mtime
                        if mtime > max_time:
                            max_time = mtime
                    except OSError:
                        pass
        except Exception as e:
            self.log(f"Error scanning files: {e}")
        return max_time

    def run_daemon(self):
        self.last_mtime = self.get_max_mtime()
        self.log("Daemon monitoring started.")
        
        while self.is_monitoring:
            time.sleep(5)
            current_max_mtime = self.get_max_mtime()
            
            if current_max_mtime > self.last_mtime:
                # Changes detected
                if self.status != "Active (Writing)":
                    self.set_status("Active (Writing)")
                    self.log("Antigravity activity detected. Waiting for cooldown...")
                self.last_mtime = current_max_mtime
                self.active_cooldown_start = time.time()
            
            elif self.status == "Active (Writing)" and self.active_cooldown_start:
                elapsed = time.time() - self.active_cooldown_start
                cooldown = self.config.get("cooldown_seconds", 30)
                if elapsed >= cooldown:
                    self.log(f"Cooldown of {cooldown}s completed. Starting auto-sync...")
                    self.set_status("Syncing")
                    
                    # Run sync in thread
                    threading.Thread(target=self.perform_backup_and_push).start()

    def set_status(self, new_status):
        self.status = new_status
        if not self.headless and hasattr(self, "status_label"):
            try:
                self.status_label.config(text=f"Status: {self.status}")
                # Color status indicator
                color = "green" if "Idle" in self.status or "Synced" in self.status else "blue" if "Active" in self.status else "orange" if "Syncing" in self.status else "red"
                self.status_indicator.config(bg=color)
            except Exception:
                pass
        if TRAY_AVAILABLE and hasattr(self, "tray_icon"):
            try:
                self.tray_icon.title = f"Antigravity Sync ({self.status})"
            except Exception:
                pass

    def copy_filtered_tree(self, src, dst):
        """Recursively copies files while applying exclude_patterns."""
        if not src.exists():
            return
        dst.mkdir(parents=True, exist_ok=True)
        
        for item in src.iterdir():
            # Check exclusions
            relative_path = item.relative_to(self.gemini_path)
            if any(exp in str(relative_path).replace("\\", "/") for exp in self.config["exclude_patterns"]):
                continue
            
            dst_item = dst / item.name
            if item.is_dir():
                self.copy_filtered_tree(item, dst_item)
            else:
                try:
                    shutil.copy2(item, dst_item)
                except OSError as e:
                    self.log(f"Failed to copy file {item.name}: {e}")

    def perform_backup_and_push(self):
        try:
            self.set_status("Syncing")
            self.log("Backing up local .gemini files...")
            
            # Perform local copy to backup_data
            self.copy_filtered_tree(self.gemini_path, self.backup_dir)
            
            backend = self.config.get("sync_backend", "github")
            
            if backend in ("github", "both"):
                self.log("Running Git push sequence...")
                self.run_git_push()
                
            if backend in ("google-drive", "both"):
                self.log("Running Google Drive sync...")
                self.run_google_drive_sync(direction="backup")
                
            self.last_sync_time = time.strftime("%H:%M:%S")
            if not self.headless and hasattr(self, "last_sync_label"):
                self.last_sync_label.config(text=f"Last Sync: {self.last_sync_time}")
                
            self.set_status("Idle (Synced)")
            self.log("Sync sequence completed successfully.")
            
        except Exception as e:
            self.set_status("Error")
            self.log(f"Sync failed: {e}")

    def run_git_push(self):
        try:
            # Check if git repository is initialized in workspace
            if not (self.script_dir / ".git").exists():
                self.log("Initializing git repository in workspace...")
                subprocess.run(["git", "init"], cwd=self.script_dir, check=True, capture_output=True)
                
            # Add files
            subprocess.run(["git", "add", "backup_data"], cwd=self.script_dir, check=True, capture_output=True)
            subprocess.run(["git", "add", ".gitignore"], cwd=self.script_dir, check=True, capture_output=True)
            
            # Check if there are changes to commit
            status = subprocess.run(["git", "status", "--porcelain"], cwd=self.script_dir, check=True, capture_output=True, text=True)
            if not status.stdout.strip():
                self.log("No new changes to commit in Git.")
                return
                
            # Commit
            commit_msg = f"Auto-backup: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=self.script_dir, check=True, capture_output=True)
            
            # Push
            remote = self.config.get("git_remote", "origin")
            # Try pushing to active branch
            branch_proc = subprocess.run(["git", "branch", "--show-current"], cwd=self.script_dir, check=True, capture_output=True, text=True)
            branch = branch_proc.stdout.strip() or "main"
            
            push_res = subprocess.run(["git", "push", remote, branch], cwd=self.script_dir, capture_output=True, text=True)
            if push_res.returncode != 0:
                self.log(f"Git push failed. Ensure remote is configured: {push_res.stderr.strip()}")
            else:
                self.log("Git push succeeded.")
        except Exception as e:
            self.log(f"Git operation error: {e}")

    def run_google_drive_sync(self, direction="backup"):
        gdrive_path_str = self.config.get("google_drive_path", "")
        if not gdrive_path_str:
            self.log("Google Drive path not set in config. Skipping Google Drive sync.")
            return
            
        gdrive_path = Path(gdrive_path_str)
        if not gdrive_path.exists():
            try:
                gdrive_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.log(f"Could not create Google Drive sync folder: {e}")
                return
                
        try:
            if direction == "backup":
                self.log(f"Copying backup to Google Drive: {gdrive_path}")
                # Simple recursive folder copy
                target_folder = gdrive_path / "backup_data"
                if target_folder.exists():
                    shutil.rmtree(target_folder)
                shutil.copytree(self.backup_dir, target_folder)
                self.log("Google Drive backup completed.")
            else:
                self.log(f"Restoring backup from Google Drive: {gdrive_path}")
                src_folder = gdrive_path / "backup_data"
                if src_folder.exists():
                    if self.backup_dir.exists():
                        shutil.rmtree(self.backup_dir)
                    shutil.copytree(src_folder, self.backup_dir)
                    self.log("Google Drive restore to local workspace folder completed.")
                else:
                    self.log("No backup folder found on Google Drive to restore.")
        except Exception as e:
            self.log(f"Google Drive sync error: {e}")

    def perform_restore(self):
        try:
            self.set_status("Restoring")
            self.log("Starting restore process...")
            
            backend = self.config.get("sync_backend", "github")
            
            if backend in ("github", "both"):
                self.log("Pulling latest files from Git...")
                if (self.script_dir / ".git").exists():
                    res = subprocess.run(["git", "pull"], cwd=self.script_dir, capture_output=True, text=True)
                    self.log(res.stdout.strip() or "Git pull completed.")
                else:
                    self.log("Git repo not initialized in workspace. Cannot pull.")
                    
            if backend in ("google-drive", "both"):
                self.log("Pulling latest files from Google Drive...")
                self.run_google_drive_sync(direction="restore")
                
            # Copy back to .gemini folder
            if self.backup_dir.exists():
                self.log("Merging restored files back into active .gemini directory...")
                self.restore_filtered_tree(self.backup_dir, self.gemini_path)
                self.log("Restore operation completed successfully. Active chats updated.")
                self.set_status("Idle")
            else:
                self.log("Error: No backup data folder found to restore.")
                self.set_status("Error")
        except Exception as e:
            self.log(f"Restore failed: {e}")
            self.set_status("Error")

    def restore_filtered_tree(self, src, dst):
        """Recursively copies files back to the active directory, merging them."""
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            dst_item = dst / item.name
            if item.is_dir():
                self.restore_filtered_tree(item, dst_item)
            else:
                try:
                    # Do not overwrite credentials if they somehow ended up in backup
                    if item.name in ("oauth_creds.json", "installation_id"):
                        continue
                    shutil.copy2(item, dst_item)
                except OSError as e:
                    self.log(f"Failed to restore file {item.name}: {e}")

    # GUI SETUP
    def setup_gui(self):
        self.root = tk.Tk()
        self.root.title("Antigravity Sync Dashboard")
        self.root.geometry("640x560")
        self.root.minsize(600, 520)
        self.root.configure(bg="#121214")
        
        # Style
        style = ttk.Style()
        style.theme_use("clam")
        
        # Configure combobox colors for readonly state
        style.configure("TCombobox", 
                        fieldbackground="#121214", 
                        background="#1a1a1e", 
                        foreground="#e1e1e6", 
                        arrowcolor="#8257e5", 
                        bordercolor="#29292e",
                        font=("Segoe UI", 10))
        style.map("TCombobox", 
                  fieldbackground=[("readonly", "#121214")], 
                  selectbackground=[("readonly", "#121214")], 
                  selectforeground=[("readonly", "#e1e1e6")],
                  foreground=[("readonly", "#e1e1e6")])

        # Configure scrollbar colors and shapes to be dark and modern
        style.configure("TScrollbar", 
                        gripcount=0,
                        background="#1a1a1e", 
                        troughcolor="#121214", 
                        bordercolor="#29292e", 
                        lightcolor="#1a1a1e", 
                        darkcolor="#1a1a1e", 
                        arrowcolor="#8257e5",
                        arrowsize=10, 
                        width=12)
        style.map("TScrollbar",
                  background=[("active", "#29292e"), ("pressed", "#8257e5")])

        # Load Window Icon
        icon_path = self.script_dir / "icon.png"
        if icon_path.exists():
            try:
                self.icon_img = ImageTk.PhotoImage(Image.open(icon_path))
                self.root.iconphoto(False, self.icon_img)
            except Exception as e:
                self.log(f"Error setting window icon: {e}")

        # Main Layout Frame
        main_frame = tk.Frame(self.root, bg="#121214", padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title header
        header_frame = tk.Frame(main_frame, bg="#121214")
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        title_label = tk.Label(header_frame, text="Antigravity Sync", bg="#121214", fg="#8257e5", font=("Segoe UI", 16, "bold"))
        title_label.pack(side=tk.LEFT)
        
        subtitle_label = tk.Label(header_frame, text="• Cross-Platform Daemon", bg="#121214", fg="#a8a8b3", font=("Segoe UI", 10, "italic"))
        subtitle_label.pack(side=tk.LEFT, padx=10, pady=4)

        # Helper to create styled cards
        def make_card(parent, title):
            card = tk.LabelFrame(parent, text=f" {title} ", bg="#1a1a1e", fg="#8257e5", font=("Segoe UI", 10, "bold"), relief="flat", bd=1, highlightbackground="#29292e", highlightthickness=1)
            return card

        # Title and Status Indicator Card
        status_frame = make_card(main_frame, "Status Monitor")
        status_frame.pack(fill=tk.X, pady=(0, 15), ipady=5)
        
        # Center status controls inside the card
        status_container = tk.Frame(status_frame, bg="#1a1a1e", padx=10, pady=5)
        status_container.pack(fill=tk.X)

        self.status_indicator = tk.Frame(status_container, width=12, height=12, bg="#04d361")
        self.status_indicator.pack(side=tk.LEFT, padx=(5, 10))
        
        self.status_label = tk.Label(status_container, text=f"Status: {self.status}", bg="#1a1a1e", fg="#e1e1e6", font=("Segoe UI", 11, "bold"))
        self.status_label.pack(side=tk.LEFT)
        
        self.last_sync_label = tk.Label(status_container, text=f"Last Sync: {self.last_sync_time}", bg="#1a1a1e", fg="#a8a8b3", font=("Segoe UI", 9, "italic"))
        self.last_sync_label.pack(side=tk.RIGHT, padx=10)
        
        # Configuration Settings Card
        config_frame = make_card(main_frame, "Configuration Profile")
        config_frame.pack(fill=tk.X, pady=(0, 15), ipady=8)
        
        # Inner padding frame
        config_inner = tk.Frame(config_frame, bg="#1a1a1e", padx=15, pady=5)
        config_inner.pack(fill=tk.X)
        
        def add_label(parent, text, row, col, sticky=tk.W):
            lbl = tk.Label(parent, text=text, bg="#1a1a1e", fg="#a8a8b3", font=("Segoe UI", 10))
            lbl.grid(row=row, column=col, sticky=sticky, pady=6)
            return lbl

        def make_styled_entry(parent, val, width=25):
            ent = tk.Entry(parent, width=width, bg="#121214", fg="#e1e1e6", insertbackground="#e1e1e6", relief="flat", bd=0, highlightbackground="#29292e", highlightcolor="#8257e5", highlightthickness=1, font=("Segoe UI", 10))
            ent.insert(0, val)
            return ent

        # Sync Backend Selection
        add_label(config_inner, "Sync Backend:", 0, 0)
        self.backend_var = tk.StringVar(value=self.config.get("sync_backend", "github"))
        backend_cb = ttk.Combobox(config_inner, textvariable=self.backend_var, values=["github", "google-drive", "both"], state="readonly", width=15)
        backend_cb.grid(row=0, column=1, sticky=tk.W, pady=6, padx=10)
        
        # Git Remote Location
        add_label(config_inner, "Git Remote Name:", 1, 0)
        self.git_remote_entry = make_styled_entry(config_inner, self.config.get("git_remote", "origin"), width=20)
        self.git_remote_entry.grid(row=1, column=1, sticky=tk.W, pady=6, padx=10)
        
        # Google Drive local path
        add_label(config_inner, "Google Drive Path:", 2, 0)
        self.gdrive_entry = make_styled_entry(config_inner, self.config.get("google_drive_path", ""), width=32)
        self.gdrive_entry.grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=6, padx=10)
        
        # Custom button builder
        def create_btn(parent, text, cmd, is_primary=True):
            bg_color = "#8257e5" if is_primary else "#29292e"
            hover_color = "#9466ff" if is_primary else "#3e3e46"
            fg_color = "#ffffff" if is_primary else "#e1e1e6"
            
            btn = tk.Button(parent, text=text, command=cmd, 
                            bg=bg_color, fg=fg_color, 
                            activebackground=hover_color, activeforeground=fg_color, 
                            relief="flat", bd=0, padx=12, pady=5, 
                            font=("Segoe UI", 9, "bold"), cursor="hand2")
            btn.bind("<Enter>", lambda e: btn.config(bg=hover_color))
            btn.bind("<Leave>", lambda e: btn.config(bg=bg_color))
            return btn

        browse_btn = create_btn(config_inner, "Browse...", self.browse_gdrive, is_primary=False)
        browse_btn.grid(row=2, column=3, sticky=tk.W, pady=6, padx=(5, 0))
        
        # Cooldown seconds
        add_label(config_inner, "Cooldown (seconds):", 3, 0)
        self.cooldown_entry = make_styled_entry(config_inner, str(self.config.get("cooldown_seconds", 30)), width=8)
        self.cooldown_entry.grid(row=3, column=1, sticky=tk.W, pady=6, padx=10)
        
        # Action Buttons row
        btn_frame = tk.Frame(main_frame, bg="#121214")
        btn_frame.pack(fill=tk.X, pady=(0, 15))
        
        save_btn = create_btn(btn_frame, "Save Settings", self.gui_save_settings, is_primary=True)
        save_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        sync_btn = create_btn(btn_frame, "Force Backup Sync", lambda: threading.Thread(target=self.perform_backup_and_push).start(), is_primary=False)
        sync_btn.pack(side=tk.LEFT, padx=5)
        
        restore_btn = create_btn(btn_frame, "Force Restore Chats", lambda: threading.Thread(target=self.perform_restore).start(), is_primary=False)
        restore_btn.pack(side=tk.LEFT, padx=5)
        
        # Log view Card
        log_frame = make_card(main_frame, "Activity Console Logs")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap=tk.WORD, 
                                bg="#121214", fg="#a6accd", insertbackground="#ffffff",
                                relief="flat", bd=0, highlightbackground="#29292e", highlightthickness=1,
                                font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=5, pady=5)
        
        # Styled scrollbar
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT, pady=5, padx=(0, 5))
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # Populate log text with previous logs
        self.log_text.config(state="normal")
        for log in self.log_messages:
            self.log_text.insert(tk.END, log + "\n")
        self.log_text.config(state="disabled")
        
        # Window closing handler
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def browse_gdrive(self):
        folder = filedialog.askdirectory(title="Select Google Drive Sync Folder")
        if folder:
            self.gdrive_entry.delete(0, tk.END)
            self.gdrive_entry.insert(0, folder)

    def gui_save_settings(self):
        self.config["sync_backend"] = self.backend_var.get()
        self.config["git_remote"] = self.git_remote_entry.get()
        self.config["google_drive_path"] = self.gdrive_entry.get()
        try:
            self.config["cooldown_seconds"] = int(self.cooldown_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Cooldown must be an integer.")
            return
            
        self.save_config()
        messagebox.showinfo("Success", "Settings saved successfully.")

    def setup_tray(self):
        # Load user's custom icon if available
        icon_path = self.script_dir / "icon.png"
        image = None
        if icon_path.exists():
            try:
                # Open, resize to standard tray icon size and convert
                image = Image.open(icon_path).resize((64, 64), Image.Resampling.LANCZOS)
            except Exception as e:
                self.log(f"Error loading tray icon image: {e}")
                
        if image is None:
            # Fallback dynamic tray image
            image = Image.new("RGB", (64, 64), color=(0, 128, 255))
            draw = ImageDraw.Draw(image)
            draw.ellipse([8, 8, 56, 56], fill=(0, 200, 100))
        
        # Tray Menu
        menu = pystray.Menu(
            pystray.MenuItem("Show GUI", self.show_gui_from_tray),
            pystray.MenuItem("Sync Now", lambda: threading.Thread(target=self.perform_backup_and_push).start()),
            pystray.MenuItem("Restore Chats", lambda: threading.Thread(target=self.perform_restore).start()),
            pystray.MenuItem("Exit", self.exit_app)
        )
        
        self.tray_icon = pystray.Icon("Antigravity Sync", image, "Antigravity Sync (Idle)", menu)
        # Run tray in separate thread to prevent blocking GUI
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_gui_from_tray(self):
        self.root.deiconify()

    def on_close(self):
        # Instead of destroying, minimize to tray if available
        if TRAY_AVAILABLE:
            self.root.withdraw()
            self.log("Minimized to system tray.")
        else:
            self.exit_app()

    def exit_app(self):
        self.is_monitoring = False
        if TRAY_AVAILABLE and hasattr(self, "tray_icon"):
            self.tray_icon.stop()
        self.root.destroy()
        sys.exit(0)

if __name__ == "__main__":
    headless = "--headless" in sys.argv
    app = AntigravitySyncApp(headless=headless)
    if not headless:
        app.root.mainloop()
