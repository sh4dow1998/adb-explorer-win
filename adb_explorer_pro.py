#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import threading
import time
import re
import json
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from queue import Queue
import zipfile
import tarfile

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext
except ImportError:
    print("Installing required packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "tk"])
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

class ADBFileCopy:
    def __init__(self, root):
        self.root = root
        self.root.title("ADB File Manager Pro - Lubuntu")
        self.root.geometry("1200x800")
        self.root.resizable(True, True)
        
        # Variables principales
        self.source_file = tk.StringVar()
        self.dest_path = tk.StringVar()
        self.device_serial = tk.StringVar()
        self.current_device_path = tk.StringVar(value="/sdcard")
        self.is_copying = False
        self.copy_thread = None
        self.stop_copy = False
        self.selected_files = []
        self.history = []
        self.history_index = -1
        self.bookmarks = []
        self.transfer_queue = Queue()
        self.is_processing_queue = False
        
        # Variables de progreso
        self.progress_percent = tk.IntVar(value=0)
        self.progress_speed = tk.StringVar(value="0.00 MB/s")
        self.progress_eta = tk.StringVar(value="Calculando...")
        self.progress_status = tk.StringVar(value="Listo")
        self.progress_bytes = tk.StringVar(value="0 / 0 MB")
        self.info_label_text = tk.StringVar(value="0% - 0.00 MB/s")  # <- MOVED HERE
        
        # Estadísticas
        self.total_transferred = 0
        self.total_files = 0
        self.start_time = None
        
        # ADB path
        self.adb_path = self.find_adb()
        
        # Cargar configuración
        self.config_file = os.path.expanduser("~/.adb_file_manager_config.json")
        self.load_config()
        
        # Setup UI
        self.setup_ui()
        
        # Check ADB
        self.check_adb_connection()
        if self.device_serial.get() not in ["No device", "Error", ""]:
            self.find_android_paths()
            self.refresh_device_files()
            self.update_stats()
        
    def find_adb(self):
        """Find ADB executable"""
        possible_paths = [
            "/usr/bin/adb",
            "/usr/local/bin/adb",
            os.path.expanduser("~/Android/Sdk/platform-tools/adb"),
            os.path.expanduser("~/android-sdk-linux/platform-tools/adb")
        ]
        
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        
        try:
            result = subprocess.run(["which", "adb"], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        
        return "adb"
    
    def load_config(self):
        """Load configuration"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.bookmarks = config.get('bookmarks', [])
                    self.total_transferred = config.get('total_transferred', 0)
                    self.total_files = config.get('total_files', 0)
        except:
            pass
    
    def save_config(self):
        """Save configuration"""
        try:
            config = {
                'bookmarks': self.bookmarks,
                'total_transferred': self.total_transferred,
                'total_files': self.total_files
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except:
            pass
    
    def setup_ui(self):
        """Setup the user interface"""
        # Main container
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left panel - File browser
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=2)
        
        # Right panel - Info and logs
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=1)
        
        # ===== LEFT PANEL =====
        # Toolbar
        toolbar = ttk.Frame(left_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))
        
        # Device info
        device_frame = ttk.LabelFrame(left_frame, text="Device", padding="5")
        device_frame.pack(fill=tk.X, pady=(0, 5))
        
        device_inner = ttk.Frame(device_frame)
        device_inner.pack(fill=tk.X)
        
        ttk.Label(device_inner, text="Device:").pack(side=tk.LEFT, padx=5)
        ttk.Label(device_inner, textvariable=self.device_serial, 
                 font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(device_inner, text="🔄 Refresh", 
                  command=self.refresh_devices, width=12).pack(side=tk.RIGHT, padx=2)
        ttk.Button(device_inner, text="📊 Stats", 
                  command=self.show_stats, width=10).pack(side=tk.RIGHT, padx=2)
        
        # Navigation
        nav_frame = ttk.Frame(left_frame)
        nav_frame.pack(fill=tk.X, pady=(0, 5))
        
        # Navigation buttons
        nav_buttons = ttk.Frame(nav_frame)
        nav_buttons.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Button(nav_buttons, text="◀ Back", command=self.go_back, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(nav_buttons, text="▶ Forward", command=self.go_forward, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(nav_buttons, text="⬆ Up", command=self.go_up, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(nav_buttons, text="🏠 Home", command=self.go_home, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(nav_buttons, text="⭐ Bookmark", command=self.add_bookmark, width=10).pack(side=tk.LEFT, padx=2)
        
        # Path entry
        path_frame = ttk.Frame(left_frame)
        path_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(path_frame, text="Path:").pack(side=tk.LEFT, padx=5)
        self.path_combo = ttk.Combobox(path_frame, textvariable=self.current_device_path, 
                                      values=["/sdcard", "/storage/emulated/0"])
        self.path_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(path_frame, text="Go", command=self.navigate_to_path, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(path_frame, text="🔄", command=self.refresh_device_files, width=3).pack(side=tk.LEFT, padx=2)
        
        # File list with checkboxes
        list_frame = ttk.LabelFrame(left_frame, text="Files")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Treeview with checkbox
        columns = ("Check", "Name", "Size", "Type", "Modified")
        self.file_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        self.file_tree.heading("Check", text="✓")
        self.file_tree.heading("Name", text="Name")
        self.file_tree.heading("Size", text="Size")
        self.file_tree.heading("Type", text="Type")
        self.file_tree.heading("Modified", text="Modified")
        self.file_tree.column("Check", width=40, anchor="center")
        self.file_tree.column("Name", width=350)
        self.file_tree.column("Size", width=100)
        self.file_tree.column("Type", width=100)
        self.file_tree.column("Modified", width=150)
        
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=scrollbar.set)
        
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind events
        self.file_tree.bind("<Double-1>", self.on_file_double_click)
        self.file_tree.bind("<Button-1>", self.on_tree_click)
        self.file_tree.bind("<Control-a>", self.select_all_files)
        self.file_tree.bind("<Control-A>", self.select_all_files)
        
        # File selection info
        select_info = ttk.Frame(left_frame)
        select_info.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(select_info, text="Selected:").pack(side=tk.LEFT, padx=5)
        self.selected_count_label = ttk.Label(select_info, text="0 files")
        self.selected_count_label.pack(side=tk.LEFT, padx=5)
        ttk.Label(select_info, text="Total size:").pack(side=tk.LEFT, padx=5)
        self.selected_size_label = ttk.Label(select_info, text="0 B")
        self.selected_size_label.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(select_info, text="Select All", command=self.select_all, width=10).pack(side=tk.RIGHT, padx=2)
        ttk.Button(select_info, text="Clear All", command=self.clear_all, width=10).pack(side=tk.RIGHT, padx=2)
        
        # Source selection
        source_frame = ttk.LabelFrame(left_frame, text="Source File")
        source_frame.pack(fill=tk.X, pady=(0, 5))
        
        source_inner = ttk.Frame(source_frame)
        source_inner.pack(fill=tk.X)
        
        self.source_entry = ttk.Entry(source_inner, textvariable=self.source_file, state='readonly')
        self.source_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(source_inner, text="Set as Source", command=self.set_selected_as_source, 
                  width=12).pack(side=tk.RIGHT, padx=2)
        ttk.Button(source_inner, text="Clear", command=self.clear_selection, 
                  width=6).pack(side=tk.RIGHT, padx=2)
        
        # ===== RIGHT PANEL =====
        # Destination
        dest_frame = ttk.LabelFrame(right_frame, text="Destination (Computer)")
        dest_frame.pack(fill=tk.X, pady=(0, 5))
        
        dest_inner = ttk.Frame(dest_frame)
        dest_inner.pack(fill=tk.X)
        
        self.dest_entry = ttk.Entry(dest_inner, textvariable=self.dest_path)
        self.dest_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(dest_inner, text="📁", command=self.browse_dest, width=3).pack(side=tk.RIGHT, padx=2)
        ttk.Button(dest_inner, text="Desktop", command=lambda: self.dest_path.set(os.path.expanduser("~/Desktop")), 
                  width=8).pack(side=tk.RIGHT, padx=2)
        
        # Progress
        progress_frame = ttk.LabelFrame(right_frame, text="Progress")
        progress_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_percent, 
                                           length=400, mode='determinate')
        self.progress_bar.pack(fill=tk.X, padx=5, pady=5)
        
        info_inner = ttk.Frame(progress_frame)
        info_inner.pack(fill=tk.X, padx=5)
        
        ttk.Label(info_inner, textvariable=self.progress_status, font=("Arial", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(info_inner, textvariable=self.info_label_text).pack(anchor=tk.W)  # <- FIXED
        
        # Speed and ETA
        speed_frame = ttk.Frame(progress_frame)
        speed_frame.pack(fill=tk.X, padx=5, pady=2)
        
        ttk.Label(speed_frame, text="Speed:").pack(side=tk.LEFT)
        ttk.Label(speed_frame, textvariable=self.progress_speed).pack(side=tk.LEFT, padx=5)
        ttk.Label(speed_frame, text="ETA:").pack(side=tk.LEFT, padx=(20, 0))
        ttk.Label(speed_frame, textvariable=self.progress_eta).pack(side=tk.LEFT, padx=5)
        
        # Bytes info
        bytes_frame = ttk.Frame(progress_frame)
        bytes_frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(bytes_frame, textvariable=self.progress_bytes).pack(anchor=tk.W)
        
        # Control buttons
        control_frame = ttk.Frame(right_frame)
        control_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.copy_button = ttk.Button(control_frame, text="▶ Pull from Device", 
                                     command=self.start_copy, width=18)
        self.copy_button.pack(side=tk.LEFT, padx=2)
        
        self.push_button = ttk.Button(control_frame, text="◀ Push to Device", 
                                      command=self.push_to_device, width=18)
        self.push_button.pack(side=tk.LEFT, padx=2)
        
        self.stop_button = ttk.Button(control_frame, text="⏹ Stop", 
                                     command=self.stop_copy_operation, width=10, state='disabled')
        self.stop_button.pack(side=tk.LEFT, padx=2)
        
        ttk.Button(control_frame, text="🗑 Clear Log", command=self.clear_log, 
                  width=12).pack(side=tk.RIGHT, padx=2)
        
        # Queue
        queue_frame = ttk.LabelFrame(right_frame, text="Transfer Queue")
        queue_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.queue_listbox = tk.Listbox(queue_frame, height=4, font=("Monospace", 9))
        self.queue_listbox.pack(fill=tk.X, padx=5, pady=5)
        
        queue_buttons = ttk.Frame(queue_frame)
        queue_buttons.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        ttk.Button(queue_buttons, text="Add to Queue", command=self.add_to_queue, 
                  width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(queue_buttons, text="Process Queue", command=self.process_queue, 
                  width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(queue_buttons, text="Clear Queue", command=self.clear_queue, 
                  width=12).pack(side=tk.LEFT, padx=2)
        
        # Log
        log_frame = ttk.LabelFrame(right_frame, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, width=40, 
                                                  font=("Monospace", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Status bar
        status_bar = ttk.Frame(self.root)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.status_bar_label = ttk.Label(status_bar, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Label(status_bar, text="Files copied:").pack(side=tk.RIGHT, padx=5)
        self.files_copied_label = ttk.Label(status_bar, text="0")
        self.files_copied_label.pack(side=tk.RIGHT, padx=5)
        
        ttk.Label(status_bar, text="Total:").pack(side=tk.RIGHT, padx=5)
        self.total_transferred_label = ttk.Label(status_bar, text="0 MB")
        self.total_transferred_label.pack(side=tk.RIGHT, padx=5)
    
    def log_message(self, message, level="INFO"):
        """Add message to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] [{level}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
        self.status_bar_label.config(text=message[:100])
    
    def check_adb_connection(self):
        """Check ADB connection"""
        try:
            result = subprocess.run([self.adb_path, "devices"], 
                                   capture_output=True, text=True, timeout=5)
            lines = result.stdout.strip().split('\n')
            devices = [line.split('\t')[0] for line in lines[1:] if line.strip() and '\tdevice' in line]
            
            if devices:
                self.device_serial.set(devices[0])
                self.log_message(f"Device connected: {devices[0]}")
                return True
            else:
                self.device_serial.set("No device")
                self.log_message("No Android device found.", "WARNING")
                return False
        except Exception as e:
            self.device_serial.set("Error")
            self.log_message(f"Error checking ADB: {str(e)}", "ERROR")
            return False
    
    def refresh_devices(self):
        """Refresh device list"""
        if self.check_adb_connection():
            self.find_android_paths()
            self.refresh_device_files()
            self.update_stats()
    
    def find_android_paths(self):
        """Find available Android storage paths"""
        if self.device_serial.get() in ["No device", "Error", ""]:
            return
        
        self.log_message("Searching for Android paths...")
        paths_to_try = [
            "/sdcard",
            "/storage/emulated/0",
            "/storage/self/primary",
            "/mnt/sdcard",
            "/storage/emulated/0/Download",
            "/storage/emulated/0/DCIM",
            "/storage/emulated/0/Pictures",
            "/storage/emulated/0/Music",
            "/storage/emulated/0/Movies"
        ]
        
        found_paths = []
        for path in paths_to_try:
            try:
                cmd = [self.adb_path, "-s", self.device_serial.get(), "shell", 
                       f"test -d '{path}' && echo 'exists'"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if "exists" in result.stdout:
                    found_paths.append(path)
                    self.log_message(f"Found path: {path}")
            except:
                continue
        
        if found_paths:
            self.path_combo['values'] = found_paths
            self.current_device_path.set(found_paths[0])
            self.log_message(f"Using path: {found_paths[0]}")
        else:
            self.log_message("No Android paths found", "WARNING")
    
    def navigate_to_path(self):
        """Navigate to path"""
        path = self.current_device_path.get().strip()
        if not path:
            return
        
        # Add to history
        if not self.history or self.history[-1] != path:
            self.history.append(path)
            self.history_index = len(self.history) - 1
        
        try:
            check_cmd = [self.adb_path, "-s", self.device_serial.get(), "shell", 
                        f"test -d '{path}' && echo 'exists'"]
            result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=5)
            if "exists" in result.stdout:
                self.refresh_device_files()
            else:
                messagebox.showerror("Error", f"Path '{path}' does not exist")
        except Exception as e:
            self.log_message(f"Error navigating: {str(e)}", "ERROR")
    
    def go_back(self):
        """Go back in history"""
        if self.history_index > 0:
            self.history_index -= 1
            self.current_device_path.set(self.history[self.history_index])
            self.refresh_device_files()
    
    def go_forward(self):
        """Go forward in history"""
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.current_device_path.set(self.history[self.history_index])
            self.refresh_device_files()
    
    def go_up(self):
        """Go up one directory"""
        current = self.current_device_path.get()
        if current in ["/", ""]:
            return
        parent = os.path.dirname(current)
        if parent == "":
            parent = "/"
        self.current_device_path.set(parent)
        self.navigate_to_path()
    
    def go_home(self):
        """Go to home"""
        for path in ["/storage/emulated/0", "/sdcard", "/storage/self/primary"]:
            try:
                check_cmd = [self.adb_path, "-s", self.device_serial.get(), "shell", 
                            f"test -d '{path}' && echo 'exists'"]
                result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=3)
                if "exists" in result.stdout:
                    self.current_device_path.set(path)
                    self.navigate_to_path()
                    return
            except:
                continue
        self.current_device_path.set("/sdcard")
        self.navigate_to_path()
    
    def add_bookmark(self):
        """Add current path to bookmarks"""
        path = self.current_device_path.get()
        if path not in self.bookmarks:
            self.bookmarks.append(path)
            self.save_config()
            self.log_message(f"Bookmark added: {path}")
            # Update combo values
            all_values = list(self.path_combo['values']) + [path]
            self.path_combo['values'] = list(set(all_values))
    
    def refresh_device_files(self):
        """Refresh file list with checkbox support"""
        if self.device_serial.get() in ["No device", "Error", ""]:
            return
        
        # Clear tree
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        
        try:
            path = self.current_device_path.get()
            self.log_message(f"Listing: {path}")
            
            cmd = [self.adb_path, "-s", self.device_serial.get(), "shell", 
                   f"ls -la '{path}' 2>/dev/null"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if not result.stdout.strip():
                self.log_message("Directory empty or inaccessible", "WARNING")
                return
            
            lines = result.stdout.strip().split('\n')
            start = 1 if lines and lines[0].startswith('total') else 0
            
            for line in lines[start:]:
                if not line.strip():
                    continue
                
                parts = line.split()
                if len(parts) < 8:
                    continue
                
                try:
                    perms = parts[0]
                    size = parts[4]
                    
                    # Detect date format
                    if len(parts[5]) == 10 and '-' in parts[5]:
                        date = parts[5]
                        time_str = parts[6]
                        name_start = 7
                        mod_date = f"{date} {time_str}"
                    else:
                        month = parts[5]
                        day = parts[6]
                        time_str = parts[7]
                        name_start = 8
                        mod_date = f"{month} {day} {time_str}"
                    
                    name = ' '.join(parts[name_start:]) if len(parts) > name_start else ""
                    
                    if not name or name in [".", ".."]:
                        continue
                    
                    is_dir = perms.startswith('d')
                    file_type = "Directory" if is_dir else "File"
                    name_display = name + "/" if is_dir else name
                    
                    if is_dir:
                        size_str = "<DIR>"
                    else:
                        try:
                            size_str = self.format_size(int(size))
                        except:
                            size_str = size
                    
                    full_path = f"{path}/{name}" if not path.endswith('/') else f"{path}{name}"
                    full_path = full_path.replace('//', '/')
                    
                    # Insert with checkbox (empty checkbox initially)
                    item_id = self.file_tree.insert("", "end", values=("☐", name_display, size_str, file_type, mod_date))
                    self.file_tree.item(item_id, tags=(full_path, name, str(is_dir).lower(), "0"))
                    
                except Exception as e:
                    continue
            
            self.log_message(f"Found {len(self.file_tree.get_children())} items")
            self.update_selection_info()
            
        except Exception as e:
            self.log_message(f"Error listing: {str(e)}", "ERROR")
    
    def on_tree_click(self, event):
        """Handle click on treeview for checkbox toggling"""
        region = self.file_tree.identify_region(event.x, event.y)
        if region == "cell":
            column = self.file_tree.identify_column(event.x)
            if column == "#1":  # Checkbox column
                item = self.file_tree.identify_row(event.y)
                if item:
                    self.toggle_checkbox(item)
    
    def toggle_checkbox(self, item):
        """Toggle checkbox state"""
        values = list(self.file_tree.item(item, "values"))
        current = values[0]
        if current == "☐":
            values[0] = "☑"
            # Update tag
            tags = list(self.file_tree.item(item, "tags"))
            tags[3] = "1"
            self.file_tree.item(item, tags=tuple(tags))
        else:
            values[0] = "☐"
            tags = list(self.file_tree.item(item, "tags"))
            tags[3] = "0"
            self.file_tree.item(item, tags=tuple(tags))
        
        self.file_tree.item(item, values=values)
        self.update_selection_info()
    
    def select_all(self):
        """Select all files"""
        for item in self.file_tree.get_children():
            values = list(self.file_tree.item(item, "values"))
            values[0] = "☑"
            self.file_tree.item(item, values=values)
            tags = list(self.file_tree.item(item, "tags"))
            tags[3] = "1"
            self.file_tree.item(item, tags=tuple(tags))
        self.update_selection_info()
    
    def clear_all(self):
        """Clear all selections"""
        for item in self.file_tree.get_children():
            values = list(self.file_tree.item(item, "values"))
            values[0] = "☐"
            self.file_tree.item(item, values=values)
            tags = list(self.file_tree.item(item, "tags"))
            tags[3] = "0"
            self.file_tree.item(item, tags=tuple(tags))
        self.update_selection_info()
    
    def select_all_files(self, event=None):
        """Select all files (Ctrl+A)"""
        self.select_all()
        return "break"
    
    def update_selection_info(self):
        """Update selection info"""
        selected = []
        total_size = 0
        
        for item in self.file_tree.get_children():
            tags = self.file_tree.item(item, "tags")
            if tags and len(tags) > 3 and tags[3] == "1":
                values = self.file_tree.item(item, "values")
                if len(values) > 2 and values[2] != "<DIR>":
                    try:
                        size_str = values[2].replace(" B", "").replace(" KB", "").replace(" MB", "").replace(" GB", "")
                        size = float(size_str)
                        if "KB" in values[2]:
                            size *= 1024
                        elif "MB" in values[2]:
                            size *= 1024 * 1024
                        elif "GB" in values[2]:
                            size *= 1024 * 1024 * 1024
                        total_size += size
                    except:
                        pass
                selected.append(item)
        
        self.selected_count_label.config(text=f"{len(selected)} files")
        self.selected_size_label.config(text=self.format_size(total_size))
        
        # Update source file if only one selected
        if len(selected) == 1:
            tags = self.file_tree.item(selected[0], "tags")
            if tags and len(tags) > 1:
                self.source_file.set(tags[0])
                self.source_entry.config(state='normal')
                self.source_entry.delete(0, tk.END)
                self.source_entry.insert(0, tags[0])
                self.source_entry.config(state='readonly')
    
    def get_selected_files(self):
        """Get list of selected files"""
        selected = []
        for item in self.file_tree.get_children():
            tags = self.file_tree.item(item, "tags")
            if tags and len(tags) > 3 and tags[3] == "1":
                if tags[2] == "false":  # Only files, not directories
                    selected.append(tags[0])
        return selected
    
    def on_file_double_click(self, event):
        """Handle double click"""
        item = self.file_tree.selection()[0] if self.file_tree.selection() else None
        if not item:
            return
        
        tags = self.file_tree.item(item, "tags")
        if not tags or len(tags) < 3:
            return
        
        full_path = tags[0]
        name = tags[1]
        is_dir = tags[2] == "true"
        
        if is_dir:
            self.current_device_path.set(full_path)
            self.navigate_to_path()
        else:
            self.source_file.set(full_path)
            self.source_entry.config(state='normal')
            self.source_entry.delete(0, tk.END)
            self.source_entry.insert(0, full_path)
            self.source_entry.config(state='readonly')
            self.log_message(f"Selected: {full_path}")
            
            filename = os.path.basename(full_path)
            self.dest_path.set(os.path.expanduser(f"~/Desktop/{filename}"))
    
    def set_selected_as_source(self):
        """Set selected as source"""
        selected = self.file_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Select a file first")
            return
        
        item = selected[0]
        tags = self.file_tree.item(item, "tags")
        if not tags or len(tags) < 3:
            return
        
        full_path = tags[0]
        name = tags[1]
        is_dir = tags[2] == "true"
        
        if is_dir:
            messagebox.showwarning("Warning", "Cannot select a directory")
            return
        
        self.source_file.set(full_path)
        self.source_entry.config(state='normal')
        self.source_entry.delete(0, tk.END)
        self.source_entry.insert(0, full_path)
        self.source_entry.config(state='readonly')
        
        self.log_message(f"Source set: {full_path}")
        filename = os.path.basename(full_path)
        self.dest_path.set(os.path.expanduser(f"~/Desktop/{filename}"))
    
    def clear_selection(self):
        """Clear selection"""
        self.source_file.set("")
        self.source_entry.config(state='normal')
        self.source_entry.delete(0, tk.END)
        self.source_entry.config(state='readonly')
    
    def browse_dest(self):
        """Browse destination"""
        folder = filedialog.askdirectory(initialdir=os.path.expanduser("~/Desktop"))
        if folder:
            if self.source_file.get():
                filename = os.path.basename(self.source_file.get())
                self.dest_path.set(os.path.join(folder, filename))
            else:
                self.dest_path.set(folder)
    
    def get_file_size(self, filename):
        """Get file size from device"""
        try:
            cmd = [self.adb_path, "-s", self.device_serial.get(), "shell", 
                   f"stat -c%s '{filename}' 2>/dev/null || echo 0"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            try:
                return int(result.stdout.strip())
            except:
                return 0
        except:
            return 0
    
    def format_size(self, size_bytes):
        """Format size"""
        try:
            size_bytes = int(size_bytes)
        except:
            return "0 B"
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"
    
    def format_time(self, seconds):
        """Format time"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds//60)}m {int(seconds%60)}s"
        else:
            return f"{int(seconds//3600)}h {int((seconds%3600)//60)}m"
    
    def update_progress_gui(self, percent, speed_mb, eta_seconds, status, bytes_copied=0, total_bytes=0):
        """Update progress GUI"""
        self.progress_percent.set(percent)
        
        if speed_mb > 0:
            self.progress_speed.set(f"{speed_mb:.2f} MB/s")
        else:
            self.progress_speed.set("Calculando...")
        
        if eta_seconds > 0:
            self.progress_eta.set(self.format_time(eta_seconds))
        else:
            self.progress_eta.set("Calculando...")
        
        self.progress_status.set(status)
        
        if bytes_copied > 0 and total_bytes > 0:
            self.progress_bytes.set(f"{self.format_size(bytes_copied)} / {self.format_size(total_bytes)}")
        
        info_text = f"{percent}%"
        if speed_mb > 0:
            info_text += f" - {speed_mb:.2f} MB/s"
        if eta_seconds > 0:
            info_text += f" - ETA: {self.format_time(eta_seconds)}"
        self.info_label_text.set(info_text)
        
        self.root.update_idletasks()
        self.root.update()
    
    def add_to_queue(self):
        """Add selected files to queue"""
        selected = self.get_selected_files()
        if not selected:
            messagebox.showwarning("Warning", "Select files to add to queue")
            return
        
        if not self.dest_path.get():
            messagebox.showwarning("Warning", "Set destination path first")
            return
        
        for file_path in selected:
            dest = os.path.join(self.dest_path.get(), os.path.basename(file_path))
            self.transfer_queue.put(('pull', file_path, dest))
            self.queue_listbox.insert(tk.END, f"📥 {os.path.basename(file_path)}")
        
        self.log_message(f"Added {len(selected)} files to queue")
        self.update_stats()
    
    def clear_queue(self):
        """Clear queue"""
        while not self.transfer_queue.empty():
            try:
                self.transfer_queue.get_nowait()
            except:
                break
        self.queue_listbox.delete(0, tk.END)
        self.log_message("Queue cleared")
    
    def process_queue(self):
        """Process transfer queue"""
        if self.is_processing_queue:
            return
        
        if self.transfer_queue.empty():
            messagebox.showinfo("Info", "Queue is empty")
            return
        
        self.is_processing_queue = True
        threading.Thread(target=self._process_queue_thread, daemon=True).start()
    
    def _process_queue_thread(self):
        """Process queue in thread"""
        self.log_message("Processing queue...")
        total = self.transfer_queue.qsize()
        processed = 0
        
        while not self.transfer_queue.empty() and not self.stop_copy:
            try:
                action, source, dest = self.transfer_queue.get(timeout=1)
                processed += 1
                self.log_message(f"Queue {processed}/{total}: {os.path.basename(source)}")
                
                if action == 'pull':
                    self._copy_single_file(source, dest)
                elif action == 'push':
                    self._push_single_file(source, dest)
                
                self.queue_listbox.delete(0)
                self.root.update_idletasks()
                
            except Exception as e:
                self.log_message(f"Queue error: {str(e)}", "ERROR")
        
        self.is_processing_queue = False
        self.log_message("Queue processing complete!")
        self.root.after(0, lambda: messagebox.showinfo("Success", "Queue processing complete!"))
    
    def push_to_device(self):
        """Push file to device"""
        if not self.source_file.get():
            messagebox.showerror("Error", "Select a source file first")
            return
        
        if not self.current_device_path.get():
            messagebox.showerror("Error", "Select device path first")
            return
        
        # Ask for destination on device
        dest_on_device = filedialog.askstring("Destination on Device", 
                                             f"Destination path on device:\n{self.current_device_path.get()}/")
        if not dest_on_device:
            return
        
        if not dest_on_device.startswith('/'):
            dest_on_device = '/' + dest_on_device
        
        # Copy to queue or direct
        if messagebox.askyesno("Queue", "Add to queue or copy directly?", 
                              detail="Yes = Add to queue, No = Copy directly"):
            self.transfer_queue.put(('push', self.source_file.get(), dest_on_device))
            self.queue_listbox.insert(tk.END, f"📤 {os.path.basename(self.source_file.get())}")
            self.log_message(f"Added push to queue: {self.source_file.get()} -> {dest_on_device}")
        else:
            threading.Thread(target=self._push_single_file, 
                           args=(self.source_file.get(), dest_on_device), daemon=True).start()
    
    def _push_single_file(self, source, dest):
        """Push a single file to device"""
        if not os.path.exists(source):
            self.log_message(f"File not found: {source}", "ERROR")
            return
        
        total_size = os.path.getsize(source)
        self.log_message(f"Pushing: {os.path.basename(source)} ({self.format_size(total_size)})")
        self.log_message(f"To: {dest}")
        
        self.root.after(0, lambda: self.copy_button.config(state='disabled'))
        self.root.after(0, lambda: self.stop_button.config(state='normal'))
        
        start_time = time.time()
        
        try:
            cmd = [self.adb_path, "-s", self.device_serial.get(), "push", source, dest]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1, universal_newlines=True)
            
            last_size = 0
            
            while True:
                if self.stop_copy:
                    process.terminate()
                    self.log_message("Push stopped by user", "WARNING")
                    self.update_progress_gui(0, 0, 0, "Detenido")
                    return
                
                if process.poll() is not None:
                    break
                
                # Check progress from device - usamos estimación por tiempo
                elapsed = time.time() - start_time
                if elapsed > 0 and total_size > 0:
                    # Estimamos progreso basado en velocidad promedio
                    speed = total_size / elapsed / (1024 * 1024) if elapsed > 0 else 0
                    # Usamos una estimación basada en el tiempo
                    estimated_progress = min(100, int((elapsed / (total_size / (10 * 1024 * 1024))) * 100))
                    progress = min(95, estimated_progress)  # Dejamos 5% para el final
                    eta = (total_size - (speed * elapsed * 1024 * 1024)) / (speed * 1024 * 1024) if speed > 0 else 0
                    self.update_progress_gui(progress, speed, eta, f"Pushing... {progress}%", 
                                            int(speed * elapsed * 1024 * 1024), total_size)
                
                time.sleep(0.3)
            
            process.wait()
            
            if not self.stop_copy and process.returncode == 0:
                self.update_progress_gui(100, 0, 0, "¡Completado!", total_size, total_size)
                self.log_message("Push completed successfully!", "SUCCESS")
                self.total_transferred += total_size
                self.total_files += 1
                self.save_config()
                self.update_stats()
                self.root.after(0, lambda: messagebox.showinfo("Success", "File pushed successfully!"))
            elif process.returncode != 0:
                error = process.stderr.read().strip() if process.stderr else "Unknown error"
                self.log_message(f"Push failed: {error}", "ERROR")
            
        except Exception as e:
            self.log_message(f"Error pushing: {str(e)}", "ERROR")
        
        finally:
            self.root.after(0, self.copy_complete)
    
    def _copy_single_file(self, source, dest):
        """Copy a single file with progress"""
        total_size = self.get_file_size(source)
        if total_size == 0:
            self.log_message(f"Cannot read file: {source}", "ERROR")
            return
        
        self.log_message(f"Copying: {os.path.basename(source)} ({self.format_size(total_size)})")
        self.log_message(f"From: {source}")
        self.log_message(f"To: {dest}")
        
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except:
                pass
        
        start_time = time.time()
        
        try:
            cmd = [self.adb_path, "-s", self.device_serial.get(), "pull", source, dest]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1, universal_newlines=True)
            
            last_size = 0
            
            while True:
                if self.stop_copy:
                    process.terminate()
                    self.log_message("Copy stopped by user", "WARNING")
                    self.update_progress_gui(0, 0, 0, "Detenido")
                    return
                
                if process.poll() is not None:
                    break
                
                if os.path.exists(dest):
                    current_size = os.path.getsize(dest)
                    
                    if current_size > last_size:
                        elapsed = time.time() - start_time
                        percent = int((current_size / total_size) * 100)
                        if percent > 100:
                            percent = 100
                        
                        speed = current_size / elapsed / (1024 * 1024) if elapsed > 0 else 0
                        eta = (total_size - current_size) / (speed * 1024 * 1024) if speed > 0 else 0
                        
                        self.update_progress_gui(percent, speed, eta, f"Copying... {percent}%", 
                                                current_size, total_size)
                        
                        if percent % 10 == 0 and percent > 0 and percent != int((last_size / total_size) * 100):
                            self.log_message(f"Progress: {percent}% - {speed:.2f} MB/s")
                        
                        last_size = current_size
                        
                        if current_size >= total_size:
                            self.update_progress_gui(100, speed, 0, "¡Completado!", total_size, total_size)
                            self.log_message("Copy completed!", "SUCCESS")
                            self.total_transferred += total_size
                            self.total_files += 1
                            self.save_config()
                            self.update_stats()
                            break
                
                time.sleep(0.3)
            
            process.wait()
            
            if not self.stop_copy and process.returncode == 0:
                if os.path.exists(dest):
                    final_size = os.path.getsize(dest)
                    if final_size == total_size:
                        self.update_progress_gui(100, 0, 0, "¡Completado!", total_size, total_size)
                        self.log_message("Copy completed successfully!", "SUCCESS")
                    else:
                        self.log_message(f"Size mismatch: {final_size} vs {total_size}", "ERROR")
                else:
                    self.log_message("Destination file not found", "ERROR")
            
        except Exception as e:
            self.log_message(f"Error copying: {str(e)}", "ERROR")
    
    def copy_file_with_progress(self):
        """Main copy function"""
        source = self.source_file.get()
        dest = self.dest_path.get()
        
        if not source or not dest:
            self.log_message("Source or destination not set", "ERROR")
            self.copy_complete()
            return
        
        self._copy_single_file(source, dest)
        self.copy_complete()
    
    def copy_complete(self):
        """Finish copy"""
        self.is_copying = False
        self.copy_button.config(state='normal')
        self.push_button.config(state='normal')
        self.stop_button.config(state='disabled')
        self.progress_status.set("Listo")
        self.update_stats()
    
    def start_copy(self):
        """Start copy"""
        if self.is_copying:
            return
        
        if not self.source_file.get():
            messagebox.showerror("Error", "Select a source file first")
            return
        
        if not self.dest_path.get():
            messagebox.showerror("Error", "Select a destination path")
            return
        
        self.is_copying = True
        self.stop_copy = False
        self.copy_button.config(state='disabled')
        self.push_button.config(state='disabled')
        self.stop_button.config(state='normal')
        
        self.update_progress_gui(0, 0, 0, "Iniciando...")
        
        self.copy_thread = threading.Thread(target=self.copy_file_with_progress, daemon=True)
        self.copy_thread.start()
    
    def stop_copy_operation(self):
        """Stop copy"""
        if self.is_copying:
            self.stop_copy = True
            self.log_message("Stopping...", "WARNING")
            self.stop_button.config(state='disabled')
    
    def update_stats(self):
        """Update statistics"""
        self.files_copied_label.config(text=str(self.total_files))
        self.total_transferred_label.config(text=self.format_size(self.total_transferred))
    
    def show_stats(self):
        """Show statistics dialog"""
        stats = f"""📊 Transfer Statistics

📁 Total files copied: {self.total_files}
💾 Total data transferred: {self.format_size(self.total_transferred)}
📱 Device: {self.device_serial.get()}
📂 Current path: {self.current_device_path.get()}
⭐ Bookmarks: {len(self.bookmarks)}

History entries: {len(self.history)}
Queue items: {self.transfer_queue.qsize()}
"""
        messagebox.showinfo("Statistics", stats)
    
    def clear_log(self):
        """Clear log"""
        self.log_text.delete(1.0, tk.END)

def main():
    """Main function"""
    try:
        root = tk.Tk()
        app = ADBFileCopy(root)
        root.mainloop()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
