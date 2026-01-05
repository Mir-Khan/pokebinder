import os, json, requests, webbrowser, threading, urllib.parse, re, logging, sys
import subprocess
from logging.handlers import RotatingFileHandler
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from PIL import Image, ImageTk

# --- SELF-TEST MODE ---
# Used by the updater to verify the exe is valid before installing
if "--self-test" in sys.argv:
    sys.exit(0)

# ==========================================
# LOGGING CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        # Limit log file to 2MB, keep 1 backup file. 
        # This prevents the log from ballooning in size over time.
        RotatingFileHandler("tcg_debug.log", maxBytes=2*1024*1024, backupCount=1),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Data file for users and binders
SAVE_FILE = "tcg_data.json"
CACHE_DIR = "card_cache"
MAX_CACHE_FILES = 300 # Limit cache to 300 images to save disk space

# --- UPDATE CONFIGURATION ---
# CHANGE ON NEW RELEASES
CURRENT_VERSION = os.environ.get("TCG_APP_VERSION", "1.0.0")
GITHUB_REPO = os.environ.get("TCG_GITHUB_REPO", "Mir-Khan/pokebinder")

if not os.path.exists(CACHE_DIR): 
    os.makedirs(CACHE_DIR)
    logger.info(f"Created cache directory: {CACHE_DIR}")

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class TCGApp:
    def __init__(self, root):
        logger.info("Initializing TCGApp...")
        
        # --- Windows High DPI Fix (Makes it look good on Win 10/11) ---
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass # Fails gracefully on older Windows or non-Windows

        self.root = root
        self.root.title("PokeBinder")
         # --- Set Window Icon ---
        # You must have a file named 'app.ico' in your project folder
        icon_path = resource_path("app.ico")
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)

        self.root.geometry("1600x900")
        
        # --- Drag and Drop State ---
        self.drag_data = {"card": None, "origin_idx": None, "is_binder": False, "widget": None}
        self.drag_ghost = None
        self.last_hovered_slot = None
        
        # --- Application State ---
        self.data = self.load_all_data()
        self.authenticated = False 
        
        user_list = list(self.data.keys())
        self.current_user = user_list[0] if user_list else "DefaultUser"
        self.current_binder_name = "Main Binder"
        
        self.ensure_user_exists()

        # --- UI Variables ---
        self.dark_mode = tk.BooleanVar(value=True)
        self.themes = {
            "solar": {
                "bg": "#FFFBE6", "fg": "#5C4033", "accent": "#FFA500", "card_bg": "#FFFFFF", 
                "btn": "#FFD700", "hl": "#FFD700", "owned": "#4CAF50", "text": "#000000", 
                "menu": "#F0EAD6", "overflow": "#8B4513",
                # New UI Elements
                "input_bg": "#FFFFFF", "input_fg": "#000000", "frame_fg": "#8D6E63",
                "btn_text": "#FFFFFF", "btn_success": "#81C784", "btn_danger": "#E57373", 
                "btn_info": "#64B5F6", "btn_neutral": "#B0BEC5",
                # Progress Colors (Darker for light bg)
                "prog_100": "#2E7D32", "prog_75": "#43A047", "prog_50": "#F9A825", "prog_25": "#EF6C00", "prog_0": "#C62828"
            },
            "lunar": {
                "bg": "#1A1A2E", "fg": "#E0E0E0", "accent": "#BB86FC", "card_bg": "#16213E", 
                "btn": "#3E4A89", "hl": "#FFD700", "owned": "#2E7D32", "text": "#FFFFFF", 
                "menu": "#0F3460", "overflow": "#450000",
                # New UI Elements
                "input_bg": "#2E2E4E", "input_fg": "#FFFFFF", "frame_fg": "#A0A0A0",
                "btn_text": "#FFFFFF", "btn_success": "#2E7D32", "btn_danger": "#C62828", 
                "btn_info": "#1565C0", "btn_neutral": "#455A64",
                # Progress Colors (Lighter for dark bg)
                "prog_100": "#69F0AE", "prog_75": "#66BB6A", "prog_50": "#FFCA28", "prog_25": "#FFA726", "prog_0": "#EF5350"
            }
        }
        
        self.b_rows, self.b_cols = tk.StringVar(value="3"), tk.StringVar(value="3")
        self.b_total_pages = tk.StringVar(value="10")
        self.s_rows, self.s_cols = tk.StringVar(value="3"), tk.StringVar(value="3")
        
        self.jump_search_var = tk.StringVar(value="1")
        self.jump_binder_var = tk.StringVar(value="1")
        self.max_search_pages_var = tk.StringVar(value="Max: 1")
        self.max_binder_pages_var = tk.StringVar(value="Max: 1")
        
        self.binder_title_var = tk.StringVar(value=self.current_binder_name.upper())
        
        # Debounce timers
        self._search_filter_timer = None
        self._binder_filter_timer = None

        def on_search_filter_change(*args):
            if self._search_filter_timer:
                self.root.after_cancel(self._search_filter_timer)
            self._search_filter_timer = self.root.after(600, self.apply_filter)

        def on_binder_filter_change(*args):
            if self._binder_filter_timer:
                self.root.after_cancel(self._binder_filter_timer)
            self._binder_filter_timer = self.root.after(600, lambda: self.apply_binder_filter(reset_page=True))

        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", on_search_filter_change)
        
        self.binder_filter_var = tk.StringVar()
        self.binder_filter_var.trace_add("write", on_binder_filter_change)
        
        self.status_var = tk.StringVar(value="Ready")
        self.progress_text = tk.StringVar(value="No set loaded")
        self.progress_scroll_var = tk.StringVar(value="No set loaded") # UI Display variable
        self._ticker_job = None # Handle for the scrolling animation
        self.binder_page, self.search_page = 1, 1
        
        # --- Card Data Containers ---
        self.full_set_data = [] 
        self.display_search_data = [] 
        self.refresh_current_binder_lists()
        self.current_set_name = ""
        
        self.menu_visible = True
        self.setup_ui()
        self.apply_theme()
        
        # --- Events ---
        self.root.bind("<Configure>", lambda e: self.on_resize(e))
        self.root.after(100, self.switch_user)

        # Start background cache cleanup
        threading.Thread(target=self.cleanup_cache, daemon=True).start()

        logger.info("UI Setup complete.")
    
    def cleanup_cache(self):
        """Deletes oldest files if cache exceeds MAX_CACHE_FILES"""
        try:
            files = [os.path.join(CACHE_DIR, f) for f in os.listdir(CACHE_DIR)]
            if len(files) > MAX_CACHE_FILES:
                # Sort by modification time (oldest first)
                files.sort(key=os.path.getmtime)
                # Delete excess files
                for f in files[:-MAX_CACHE_FILES]:
                    try: os.remove(f)
                    except: pass
                logger.info(f"Cache cleanup: Removed {len(files) - MAX_CACHE_FILES} old images.")
        except Exception as e:
            logger.error(f"Cache cleanup failed: {e}")

    # ==========================================
    # SCROLLING & RESIZE LOGIC
    # ==========================================
    def _on_mousewheel(self, event, canvas):
        if event.num == 4: canvas.yview_scroll(-1, "units")
        elif event.num == 5: canvas.yview_scroll(1, "units")
        else: canvas.yview_scroll(1 if event.delta < 0 else -1, "units")

    def bind_tree_to_scroll(self, widget, canvas):
        widget.bind("<MouseWheel>", lambda e: self._on_mousewheel(e, canvas))
        widget.bind("<Button-4>", lambda e: self._on_mousewheel(e, canvas))
        widget.bind("<Button-5>", lambda e: self._on_mousewheel(e, canvas))
        for child in widget.winfo_children(): self.bind_tree_to_scroll(child, canvas)

    def on_resize(self, event):
        if hasattr(self, 'left_pane'): self.update_scroll_region(self.left_pane['canvas'])
        if hasattr(self, 'right_pane'): self.update_scroll_region(self.right_pane['canvas'])

    def update_scroll_region(self, canvas):
        canvas.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

    # ==========================================
    # BINDER MANAGEMENT ACTIONS
    # ==========================================
    def apply_binder_grid(self):
        try:
            rows = int(self.b_rows.get())
            cols = int(self.b_cols.get())
            pages = int(self.b_total_pages.get())
            if rows <= 0 or cols <= 0 or pages <= 0:
                raise ValueError("Rows, columns, and pages must be positive integers.")
            
            logger.info(f"Applying binder grid: {rows} rows x {cols} cols x {pages} pages")
            
            # Save layout configuration
            user_data = self.data[self.current_user]
            if "binder_layouts" not in user_data: user_data["binder_layouts"] = {}
            user_data["binder_layouts"][self.current_binder_name] = {"rows": rows, "cols": cols, "pages": pages}
            self.save_all_data()
            
            # Re-render the current page with the updated grid
            self.refresh_view(target="binder")
        except ValueError as e:
            logger.error(f"Invalid grid size: {e}")
            messagebox.showerror("Invalid Input", "Rows, columns, and pages must be positive integers.")



    def sort_binder(self):
        logger.info(f"Sorting binder: {self.current_binder_name}")
        self.owned_cards = [c for c in self.owned_cards if c.get('id') != 'empty']
        self.owned_cards.sort(key=lambda x: x['name'].lower())
        self.data[self.current_user]["binders"][self.current_binder_name] = self.owned_cards
        self.save_all_data()
        self.apply_binder_filter(reset_page=False)
    
    def sort_binder_by_number(self):
        logger.info(f"Sorting binder by number: {self.current_binder_name}")
        
        # 1. Ensure card_number exists for all cards (Data Migration)
        for card in self.owned_cards:
            if card.get('id') != 'empty' and 'card_number' not in card:
                try:
                    # Extract from ID (e.g. "me02-129" -> "129")
                    if '-' in card['id']:
                        card['card_number'] = card['id'].split('-')[-1]
                    # Fallback: Extract from Image URL
                    elif 'image' in card:
                        match = re.search(r'/([^/]+)/low\.jpg', card['image'])
                        if match: card['card_number'] = match.group(1)
                    
                    if 'card_number' not in card: card['card_number'] = "0"
                except:
                    card['card_number'] = "0"

        # 2. Filter out empty slots
        self.owned_cards = [c for c in self.owned_cards if c.get('id') != 'empty']
        
        # 3. Sort logic (handles "1", "2", "10" correctly instead of "1", "10", "2")
        def get_num(c):
            try: 
                # Extract digits to handle variants like "12a"
                s = str(c.get('card_number', '0'))
                num_part = "".join(filter(str.isdigit, s))
                return int(num_part) if num_part else 9999
            except: return 9999

        self.owned_cards.sort(key=get_num)
        
        # 4. Update and Save to Disk
        self.data[self.current_user]["binders"][self.current_binder_name] = self.owned_cards
        self.save_all_data()
        self.apply_binder_filter(reset_page=False)

    def clear_binder(self):
        if messagebox.askyesno("Confirm", "Empty current binder?"):
            logger.warning(f"User {self.current_user} cleared binder {self.current_binder_name}")
            self.owned_cards.clear()
            self.data[self.current_user]["binders"][self.current_binder_name] = self.owned_cards
            self.save_all_data()
            self.apply_binder_filter(reset_page=True)

    def add_full_set_to_binder(self):
        if not self.full_set_data: 
            logger.info("Add Full Set cancelled: No set data loaded.")
            return
        
        try:
            capacity = int(self.b_rows.get()) * int(self.b_cols.get()) * int(self.b_total_pages.get())
            if len(self.owned_cards) + len(self.full_set_data) > capacity:
                if not messagebox.askyesno("Capacity Warning", f"Adding this set will exceed your physical binder limit.\n\nContinue?"):
                    return
        except Exception as e: 
            logger.error(f"Error calculating capacity: {e}")

        logger.info(f"Adding full set {self.current_set_name} to binder.")
        self.owned_cards.extend(self.full_set_data)
        self.save_all_data()
        self.apply_binder_filter(reset_page=False)

    # ==========================================
    # DRAG AND DROP & CONTEXT MENUS
    # ==========================================
    def show_binder_context_menu(self, event, card, idx):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=f"Move {card['name']} to Page...", command=lambda: self.prompt_move_to_page(card, idx))
        menu.add_separator()
        menu.add_command(label="Remove Card", command=lambda: self.remove_card_by_object(card))
        menu.post(event.x_root, event.y_root)

    def prompt_move_to_page(self, card, origin_idx):
        target_page = simpledialog.askinteger("Move Card", "Enter Target Page Number:", minvalue=1, maxvalue=200)
        if target_page:
            logger.debug(f"Prompting move for {card['name']} to page {target_page}")
            rows, cols = int(self.b_rows.get()), int(self.b_cols.get())
            per_page = rows * cols
            start_idx = (target_page - 1) * per_page
            end_idx = start_idx + per_page
            
            found_slot = -1
            for i in range(start_idx, end_idx):
                if i >= len(self.owned_cards) or self.owned_cards[i].get('id') == 'empty':
                    found_slot = i
                    break
            
            if found_slot == -1: found_slot = end_idx
            self.execute_move(card, origin_idx, found_slot, True)

    def on_drag_start(self, event, card, idx, is_binder):
        if is_binder and not self.authenticated: return
        logger.debug(f"Drag started: {card['name']} at index {idx}")
        self.drag_data = {"card": card, "origin_idx": idx, "is_binder": is_binder}
        self.drag_ghost = tk.Toplevel(self.root)
        self.drag_ghost.overrideredirect(True)
        self.drag_ghost.attributes("-alpha", 0.7)
        tk.Label(self.drag_ghost, text=card['name'], bg="yellow", relief="solid", borderwidth=1, padx=5).pack()
        self.on_drag_motion(event)

    def on_drag_motion(self, event):
        if self.drag_ghost:
            self.drag_ghost.geometry(f"+{event.x_root+10}+{event.y_root+10}")
            self.update_drag_highlight(event)

    def update_drag_highlight(self, event):
        target_widget = self.root.winfo_containing(event.x_root, event.y_root)
        grid_parent = None
        curr = target_widget
        while curr:
            if curr == self.left_pane['grid']:
                grid_parent = curr; break
            curr = curr.master if hasattr(curr, 'master') else None

        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        if self.last_hovered_slot:
            slot_idx = getattr(self.last_hovered_slot, 'slot_index', 0)
            try: capacity = int(self.b_rows.get()) * int(self.b_cols.get()) * int(self.b_total_pages.get())
            except: capacity = 9999
            border = t["overflow"] if slot_idx >= capacity else t["accent"]
            self.last_hovered_slot.configure(highlightbackground=border)
            self.last_hovered_slot = None

        if grid_parent:
            rel_x = event.x_root - grid_parent.winfo_rootx()
            rel_y = event.y_root - grid_parent.winfo_rooty()
            try:
                rows, cols = int(self.b_rows.get()), int(self.b_cols.get())
                sample = grid_parent.winfo_children()[0]
                sw, sh = sample.winfo_width() + 10, sample.winfo_height() + 10
                c, r = rel_x // sw, rel_y // sh
                if 0 <= c < cols and 0 <= r < rows:
                    for slot in grid_parent.winfo_children():
                        info = slot.grid_info()
                        if int(info['row']) == r and int(info['column']) == c:
                            slot.configure(highlightbackground=t["hl"])
                            self.last_hovered_slot = slot; break
            except: pass

    def on_drag_release(self, event):
        if not self.drag_ghost: return
        self.drag_ghost.destroy(); self.drag_ghost = None
        
        if self.last_hovered_slot:
            self.last_hovered_slot = None

        target_widget = self.root.winfo_containing(event.x_root, event.y_root)
        grid_parent = None
        curr = target_widget
        while curr:
            if curr == self.left_pane['grid']:
                grid_parent = curr; break
            curr = curr.master if hasattr(curr, 'master') else None

        if grid_parent:
            rel_x = event.x_root - grid_parent.winfo_rootx()
            rel_y = event.y_root - grid_parent.winfo_rooty()
            try:
                rows, cols = int(self.b_rows.get()), int(self.b_cols.get())
                per_page = rows * cols
                sample = grid_parent.winfo_children()[0]
                sw, sh = sample.winfo_width() + 10, sample.winfo_height() + 10
                drop_col, drop_row = rel_x // sw, rel_y // sh
                
                if 0 <= drop_col < cols and 0 <= drop_row < rows:
                    target_idx = ((self.binder_page - 1) * per_page) + (drop_row * cols + drop_col)
                    logger.info(f"Card dropped at target index {target_idx}")
                    self.execute_move(self.drag_data['card'], self.drag_data['origin_idx'], target_idx, self.drag_data['is_binder'])
            except Exception as e: 
                logger.error(f"Drag release failed: {e}")

    def execute_move(self, card, origin_idx, target_idx, was_in_binder):
        logger.debug(f"Executing move: {card['name']} from {origin_idx} to {target_idx}")
        
        while len(self.owned_cards) <= target_idx:
            self.owned_cards.append({"name": "Empty Slot", "id": "empty", "image": ""})

        if was_in_binder and origin_idx is not None:
            while len(self.owned_cards) <= origin_idx:
                self.owned_cards.append({"name": "Empty Slot", "id": "empty", "image": ""})
            self.owned_cards[origin_idx], self.owned_cards[target_idx] = self.owned_cards[target_idx], self.owned_cards[origin_idx]
        else:
            self.owned_cards[target_idx] = card

        self.save_all_data()
        self.apply_binder_filter(reset_page=False)

    # ==========================================
    # DATA PERSISTENCE (JSON)
    # ==========================================
    def load_all_data(self):
        if os.path.exists(SAVE_FILE):
            try:
                with open(SAVE_FILE, 'r') as f: 
                    logger.info("Loading user data from file.")
                    return json.load(f)
            except Exception as e: 
                logger.error(f"Failed to load JSON: {e}")
                return {}
        return {}

    def save_all_data(self):
        try:
            with open(SAVE_FILE, 'w') as f: 
                json.dump(self.data, f, indent=4)
                logger.info("Data saved successfully.")
        except Exception as e:
            logger.error(f"Failed to save data: {e}")

    def ensure_user_exists(self):
        if not self.data:
            self.data["DefaultUser"] = {"pw": "1234", "binders": {"Main Binder": []}, "order": ["Main Binder"], "binder_layouts": {"Main Binder": {"rows": 3, "cols": 3, "pages": 10}}}
        if self.current_user not in self.data:
            self.current_user = list(self.data.keys())[0]
        user_data = self.data[self.current_user]
        if "order" not in user_data: user_data["order"] = list(user_data["binders"].keys())
        if "binder_layouts" not in user_data: user_data["binder_layouts"] = {}
        
        # Initialize theme preference if missing
        if "dark_mode" not in user_data: user_data["dark_mode"] = True

        if self.current_binder_name not in user_data["binders"]:
            self.current_binder_name = user_data["order"][0]

    def refresh_current_binder_lists(self):
        self.owned_cards = self.data[self.current_user]["binders"][self.current_binder_name]
        self.display_owned_cards = self.owned_cards.copy()
        self.binder_title_var.set(self.current_binder_name.upper())
        
        # Load layout settings for this binder
        layouts = self.data[self.current_user].get("binder_layouts", {})
        layout = layouts.get(self.current_binder_name, {"rows": 3, "cols": 3, "pages": 10})
        self.b_rows.set(str(layout.get("rows", 3)))
        self.b_cols.set(str(layout.get("cols", 3)))
        self.b_total_pages.set(str(layout.get("pages", 10)))
    
    # ==========================================
    # AUTO-UPDATER LOGIC
    # ==========================================
    def check_for_updates(self, silent=False):
        """Checks GitHub for a newer release."""
        if "your-repo-name" in GITHUB_REPO:
            if not silent: messagebox.showinfo("Config Error", "Please configure GITHUB_REPO in the source code.")
            return

        logger.info("Checking for updates...")
        def _check():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    latest_tag = data['tag_name'].lstrip('v') # Remove 'v' if present
                    
                    # Simple version comparison
                    if latest_tag != CURRENT_VERSION:
                        # Find the .exe asset
                        exe_url = next((a['browser_download_url'] for a in data['assets'] if a['name'].endswith('.exe')), None)
                        
                        if exe_url:
                            self.root.after(0, lambda: self.prompt_update(latest_tag, exe_url, data['body']))
                        elif not silent:
                            self.root.after(0, lambda: messagebox.showinfo("Update", "New version detected, but no executable found."))
                    elif not silent:
                        self.root.after(0, lambda: messagebox.showinfo("Up to Date", f"You are running the latest version ({CURRENT_VERSION})."))
            except Exception as e:
                logger.error(f"Update check failed: {e}")
                if not silent: self.root.after(0, lambda: messagebox.showerror("Error", "Failed to check for updates."))
        
        threading.Thread(target=_check, daemon=True).start()

    def prompt_update(self, version, url, notes):
        msg = f"A new version ({version}) is available!\n\nRelease Notes:\n{notes}\n\nUpdate now?"
        if messagebox.askyesno("Update Available", msg):
            self.perform_update(url)

    def perform_update(self, url):
        """Downloads new exe and restarts."""
        try:
            # 1. Download the new executable
            self.status_var.set("Downloading update...")
            new_exe_name = "PokeBinder_new.exe"
            
            # Stream download to avoid freezing
            def _download():
                try:
                    r = requests.get(url, stream=True)
                    r.raise_for_status()
                    
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded = 0
                    
                    with open(new_exe_name, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                    
                    if total_size != 0 and downloaded != total_size:
                        raise Exception(f"Incomplete download: {downloaded}/{total_size} bytes")

                    logger.info("Download complete. proceeding to update.")
                    self.root.after(0, self.finalize_update, new_exe_name)
                    
                except Exception as e:
                    logger.error(f"Download failed: {e}")
                    self.root.after(0, lambda: messagebox.showerror("Update Failed", f"Error: {str(e)}"))
                    try: os.remove(new_exe_name)
                    except: pass
            
            threading.Thread(target=_download, daemon=True).start()
            
        except Exception as e:
            logger.error(f"Update init failed: {e}")

    def finalize_update(self, new_exe):
        """Creates the batch script and restarts."""
        # Safety check: Prevent running update logic if not running as compiled EXE
        if not getattr(sys, 'frozen', False):
            logger.warning("Running from source code: Update skipped to prevent deleting python.exe")
            messagebox.showinfo("Dev Mode", "Update downloaded, but restart skipped because you are running from source.")
            return

        current_exe = os.path.basename(sys.executable)
        
        # Create a batch script that tries to DELETE the file directly.
        # This is better than tasklist because it checks the specific file lock.
        bat_script = f"""
@echo off
title PokeBinder Updater
echo Closing application...

REM Wait a generic 2 seconds for app to flush and close
timeout /t 2 /nobreak >nul

:TRY_DELETE
echo Attempting to replace old version...
REM Try to delete the file. If it fails (access denied), it means it's still running.
del /f /q "{current_exe}" >nul 2>&1

if exist "{current_exe}" (
    echo File is still locked. Retrying in 1 second...
    timeout /t 1 /nobreak >nul
    goto TRY_DELETE
)

echo Update found. Installing...
move /y "{new_exe}" "{current_exe}" >nul

echo Restarting PokeBinder...
REM Give the OS/Antivirus a moment to release the new file handle
timeout /t 2 /nobreak >nul
start "" "{current_exe}"

REM Self-delete this script and exit
del "%~f0" & exit
"""
        with open("update_installer.bat", "w") as f:
            f.write(bat_script)
            
        logger.info("Starting update script and closing app.")
        os.startfile("update_installer.bat")
        
        # Forcefully kill the process
        self.root.destroy()
        os._exit(0)

    # ==========================================
    # UI CONSTRUCTION
    # ==========================================
    def setup_ui(self):
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]

        self.main_container = tk.Frame(self.root, bg=t["bg"])
        self.main_container.pack(fill="both", expand=True)

        self.menu_frame = tk.Frame(self.main_container, width=220, bg=t["menu"])
        self.menu_frame.pack(side="left", fill="y")
        self.setup_side_menu()

        self.content_frame = tk.Frame(self.main_container, bg=t["bg"])
        self.content_frame.pack(side="right", fill="both", expand=True)

        self.top = tk.Frame(self.content_frame, pady=5, bg=t["bg"])
        self.top.pack(fill="x", side="top")
        
        self.menu_btn = tk.Button(self.top, text="☰", font=("Arial", 11, "bold"), command=self.toggle_menu, 
                                  relief="flat", bg=t["btn"], fg=t["btn_text"], activebackground=t["hl"], activeforeground=t["bg"])
        self.menu_btn.pack(side="left", padx=10)

        self.theme_btn = tk.Checkbutton(self.top, text="🌙 Theme", variable=self.dark_mode, command=self.apply_theme, 
                                        indicatoron=False, bg=t["btn"], fg=t["text"], selectcolor=t["hl"], activebackground=t["hl"])
        self.theme_btn.pack(side="right", padx=10)

        self.status_lbl = tk.Label(self.top, textvariable=self.status_var, font=("Arial", 9, "italic"), bg=t["bg"], fg=t["text"])
        self.status_lbl.pack(side="right", padx=20)
        
        self.paned = tk.PanedWindow(self.content_frame, orient="horizontal", sashwidth=4, bg=t["bg"], sashrelief="flat")
        self.paned.pack(fill="both", expand=True)
        
        self.left_pane = self.create_scrollable_pane(self.paned, self.binder_title_var, "binder")
        self.right_pane = self.create_scrollable_pane(self.paned, tk.StringVar(value="Filter search"), "search")
        
        self.setup_binder_header()
        self.setup_search_header()

    def setup_binder_header(self):
        h = self.left_pane['header_tools']
        for w in h.winfo_children(): w.destroy()
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        
        # Helper functions for consistent styling
        def style_frame(parent, text):
            f = tk.LabelFrame(parent, text=text, font=("Segoe UI", 8, "bold"), padx=5, pady=2, 
                              bg=t["bg"], fg=t["frame_fg"], relief="flat", bd=1)
            f.pack(side="left", padx=5, pady=2, fill="y")
            return f

        def style_entry(parent, var, width):
            e = tk.Entry(parent, width=width, textvariable=var, bg=t["input_bg"], fg=t["input_fg"], 
                         insertbackground=t["input_fg"], relief="flat", highlightthickness=1, highlightbackground=t["frame_fg"])
            e.pack(side="left", padx=2, ipady=2)
            return e

        def style_btn(parent, text, cmd, bg_col):
            b = tk.Button(parent, text=text, command=cmd, bg=bg_col, fg=t["btn_text"], 
                          font=("Arial", 8, "bold"), relief="flat", activebackground=t["hl"], activeforeground=t["bg"], padx=8)
            b.pack(side="left", padx=2, pady=1)
            return b
        
        # --- Layout Controls Group ---
        layout_frame = style_frame(h, "Grid Layout")
        
        tk.Label(layout_frame, text="Rows:", font=("Arial", 8), bg=t["bg"], fg=t["text"]).pack(side="left")
        style_entry(layout_frame, self.b_rows, 3)
        tk.Label(layout_frame, text="Cols:", font=("Arial", 8), bg=t["bg"], fg=t["text"]).pack(side="left")
        style_entry(layout_frame, self.b_cols, 3)
        tk.Label(layout_frame, text="Pages:", font=("Arial", 8), bg=t["bg"], fg=t["text"]).pack(side="left", padx=(5, 2))
        style_entry(layout_frame, self.b_total_pages, 4)
        
        style_btn(layout_frame, "Apply", self.apply_binder_grid, t["btn_success"])

        # --- Binder Actions Group ---
        action_frame = style_frame(h, "Actions")
        
        style_btn(action_frame, "Sort A-Z", self.sort_binder, t["btn_neutral"])
        style_btn(action_frame, "Sort #", self.sort_binder_by_number, t["btn_neutral"])
        style_btn(action_frame, "Clear All", self.clear_binder, t["btn_danger"])
        style_btn(action_frame, "+ Add Loaded Set", self.add_full_set_to_binder, t["btn_success"])

    def setup_search_header(self):
        # Preserve values during theme switch
        # Check against placeholders to avoid saving them as actual values
        raw_set = self.set_entry.get() if hasattr(self, 'set_entry') and self.set_entry.winfo_exists() else ""
        current_set_val = raw_set if raw_set != "Name of set here..." else ""

        raw_search = self.card_search_entry.get() if hasattr(self, 'card_search_entry') and self.card_search_entry.winfo_exists() else ""
        current_search_val = raw_search if raw_search != "Card name..." else ""

        h = self.right_pane['header_tools']
        for w in h.winfo_children(): w.destroy()
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]

        # Helper functions (reused logic)
        def style_frame(parent, text):
            f = tk.LabelFrame(parent, text=text, font=("Segoe UI", 8, "bold"), padx=5, pady=2, 
                              bg=t["bg"], fg=t["frame_fg"], relief="flat", bd=1)
            f.pack(side="left", padx=5, pady=2, fill="y")
            return f

        def style_entry(parent, width, var=None, placeholder=None):
            e = tk.Entry(parent, width=width, textvariable=var, bg=t["input_bg"], fg=t["input_fg"], 
                         insertbackground=t["input_fg"], relief="flat", highlightthickness=1, highlightbackground=t["frame_fg"])
            e.pack(side="left", padx=2, ipady=2)
            
            if placeholder and not var:
                def on_focus_in(event):
                    if e.get() == placeholder:
                        e.delete(0, "end")
                        e.config(fg=t["input_fg"])
                
                def on_focus_out(event):
                    if not e.get():
                        e.insert(0, placeholder)
                        e.config(fg=t["frame_fg"])
                
                e.bind("<FocusIn>", on_focus_in)
                e.bind("<FocusOut>", on_focus_out)
                
                # Initialize with placeholder
                e.insert(0, placeholder)
                e.config(fg=t["frame_fg"])
            
            return e

        def style_btn(parent, text, cmd, bg_col):
            b = tk.Button(parent, text=text, command=cmd, bg=bg_col, fg=t["btn_text"], 
                          font=("Arial", 8, "bold"), relief="flat", activebackground=t["hl"], activeforeground=t["bg"], padx=8)
            b.pack(side="left", padx=2, pady=1)
            return b
        
        # --- Search Grid Group ---
        view_frame = style_frame(h, "View")
        
        tk.Label(view_frame, text="Rows:", font=("Arial", 8), bg=t["bg"], fg=t["text"]).pack(side="left")
        style_entry(view_frame, 3, self.s_rows)
        tk.Label(view_frame, text="Columns:", font=("Arial", 8), bg=t["bg"], fg=t["text"]).pack(side="left")
        style_entry(view_frame, 3, self.s_cols)
        style_btn(view_frame, "Set Search Grid", lambda: self.refresh_view(target="search"), t["btn_neutral"])

        # --- Set Loader Group ---
        load_frame = style_frame(h, "Load Set (TCGDex)")
        
        self.set_entry = style_entry(load_frame, 18, placeholder="Name of set here...")
        if current_set_val:
            self.set_entry.delete(0, "end")
            self.set_entry.insert(0, current_set_val)
            self.set_entry.config(fg=t["input_fg"])
            
        self.set_entry.bind("<Return>", self.handle_load)
        style_btn(load_frame, "Load Set", self.handle_load, t["btn_info"])

        # --- Card Search Group ---
        find_frame = style_frame(h, "Find Card")
        
        self.card_search_entry = style_entry(find_frame, 15, placeholder="Card name...")
        if current_search_val:
            self.card_search_entry.delete(0, "end")
            self.card_search_entry.insert(0, current_search_val)
            self.card_search_entry.config(fg=t["input_fg"])
            
        self.card_search_entry.bind("<Return>", self.handle_card_search)
        style_btn(find_frame, "Search", self.handle_card_search, t["btn_info"])

         # --- Status ---
        # Use progress_scroll_var and fixed width to support scrolling text
        self.progress_label = tk.Label(h, textvariable=self.progress_scroll_var, font=("Segoe UI", 9, "bold"), fg=t["owned"], bg=t["bg"], width=30, anchor="e")
        self.progress_label.pack(side="right", padx=10)

    def toggle_menu(self):
        if self.menu_visible: self.menu_frame.pack_forget()
        else: self.menu_frame.pack(side="left", fill="y", before=self.content_frame)
        self.menu_visible = not self.menu_visible

    def setup_side_menu(self):
        for w in self.menu_frame.winfo_children(): w.destroy()
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        user_sec = tk.Frame(self.menu_frame, pady=10, bg=t["menu"])
        user_sec.pack(fill="x")
        tk.Label(user_sec, text=f"👤 {self.current_user}", font=("Segoe UI", 11, "bold"), bg=t["menu"], fg=t["text"]).pack()
        tk.Button(user_sec, text=f"v{CURRENT_VERSION} (Check Updates)", command=lambda: self.check_for_updates(silent=False), 
                  font=("Arial", 7), bg=t["menu"], fg=t["accent"], relief="flat", cursor="hand2").pack(pady=2)
        tk.Button(user_sec, text="Switch User", command=self.switch_user, font=("Arial", 8), bg="#555555", fg="white").pack(pady=5)
        ttk.Separator(self.menu_frame, orient='horizontal').pack(fill='x', padx=10, pady=5)
        tk.Label(self.menu_frame, text="YOUR BINDERS", font=("Arial", 9, "bold"), bg=t["menu"], fg=t["text"]).pack(pady=5)
        for b_name in self.data[self.current_user]["order"]:
            f = tk.Frame(self.menu_frame, bg=t["menu"]); f.pack(fill="x", pady=1, padx=5)
            active = b_name == self.current_binder_name
            btn_style = {"bg": "#3E4A89", "fg": "white"} if active else {"bg": "#DDDDDD", "fg": "black"}
            tk.Button(f, text=f"📂 {b_name}", command=lambda n=b_name: self.select_binder(n), anchor="w", font=("Arial", 9), relief="flat", **btn_style).pack(side="left", fill="x", expand=True)
            tk.Button(f, text="×", command=lambda n=b_name: self.delete_binder(n), bg="#8B0000", fg="white", relief="flat", width=2, font=("Arial", 10, "bold")).pack(side="right", padx=1)
        tk.Button(self.menu_frame, text="+ Create New Binder", command=self.create_binder, bg="#2E7D32", fg="white", font=("Arial", 9, "bold")).pack(fill="x", padx=10, pady=(5, 20))

    def create_scrollable_pane(self, parent, title_var, type_name):
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        
        frame = tk.Frame(parent, bg=t["bg"]); parent.add(frame, stretch="always")
        header = tk.Frame(frame, bg=t["bg"]); header.pack(fill="x", pady=2)
        
        tk.Label(header, textvariable=title_var, font=('Segoe UI', 10, 'bold'), bg=t["bg"], fg=t["text"]).pack(side="left", padx=10)
        
        # Filter Entry with Label
        if type_name == "binder":
            tk.Label(header, text="Filter Binder:", font=("Arial", 8), bg=t["bg"], fg=t["text"]).pack(side="left", padx=(10, 2))
            
        tk.Entry(header, width=15 if type_name == "binder" else 10, textvariable=self.binder_filter_var if type_name == "binder" else self.filter_var,
                 bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_fg"], 
                 relief="flat", highlightthickness=1, highlightbackground=t["frame_fg"]).pack(side="left", padx=2)
        
        nav = tk.Frame(header, bg=t["bg"]); nav.pack(side="right", padx=10)
        
        tk.Label(nav, textvariable=self.max_binder_pages_var if type_name == "binder" else self.max_search_pages_var, 
                 font=("Arial", 8), bg=t["bg"], fg=t["text"]).pack(side="left", padx=5)
        
        btn_args = {"bg": t["btn"], "fg": t["btn_text"], "activebackground": t["hl"], "activeforeground": t["bg"], "relief": "flat", "font": ("Arial", 8)}
        
        tk.Button(nav, text="|<<", command=lambda: self.go_to_first(type_name), **btn_args).pack(side="left", padx=1)
        tk.Button(nav, text="<", command=lambda: self.change_page(type_name, -1), **btn_args).pack(side="left", padx=1)
        
        ent = tk.Entry(nav, width=3, textvariable=self.jump_binder_var if type_name == "binder" else self.jump_search_var,
                       bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_fg"], 
                       relief="flat", highlightthickness=1, highlightbackground=t["frame_fg"])
        ent.pack(side="left", padx=2); ent.bind("<Return>", lambda e: self.jump_to_page(type_name, e))
        
        tk.Button(nav, text=">", command=lambda: self.change_page(type_name, 1), **btn_args).pack(side="left", padx=1)
        tk.Button(nav, text=">>|", command=lambda: self.go_to_last(type_name), **btn_args).pack(side="left", padx=1)
        
        tools_row = tk.Frame(frame, bg=t["bg"]); tools_row.pack(fill="x", pady=2)
        container = tk.Frame(frame, bg=t["bg"]); container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0, bg=t["bg"])
        v_scroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        grid = tk.Frame(canvas, bg=t["bg"]); canvas.create_window((0, 0), window=grid, anchor="nw")
        canvas.configure(yscrollcommand=v_scroll.set)
        canvas.pack(side="left", fill="both", expand=True); v_scroll.pack(side="right", fill="y")
        return {"grid": grid, "canvas": canvas, "frame": frame, "header": header, "header_tools": tools_row, "container": container}

    # ==========================================
    # RENDERING & IMAGE CACHING
    # ==========================================
    def render_side(self, pane, data, page, is_binder, t, rows, cols):
        # logger.info(f"This is the data being rendered: {data}")
        
        # Capture card number for sorting/logic
        for card in data:
            if card.get('id') != 'empty' and 'card_number' not in card:
                try:
                    # Extract from ID (e.g. "me02-129" -> "129")
                    if '-' in card['id']:
                        card['card_number'] = card['id'].split('-')[-1]
                    # Fallback: Extract from Image URL
                    elif 'image' in card:
                        match = re.search(r'/([^/]+)/low\.jpg', card['image'])
                        if match: card['card_number'] = match.group(1)
                    
                    if 'card_number' not in card: card['card_number'] = "0"
                except:
                    card['card_number'] = "0"

        for w in pane['grid'].winfo_children(): w.destroy()
        if is_binder and not self.authenticated:
            lock_path = os.path.join("img", "locked.png")
            if os.path.exists(lock_path):
                try:
                    pil_img = Image.open(lock_path)
                    pil_img.thumbnail((400, 400)) # Resize to reasonable dimensions
                    lock_photo = ImageTk.PhotoImage(pil_img)
                    lbl = tk.Label(pane['grid'], image=lock_photo, bg=t["bg"])
                    lbl.image = lock_photo # Keep reference to prevent garbage collection
                    lbl.place(relx=0.5, rely=0.5, anchor="center")
                except Exception as e:
                    logger.error(f"Failed to load locked image: {e}")
                    tk.Label(pane['grid'], text="[ BINDER LOCKED ]", fg=t["accent"], bg=t["bg"], font=("Arial", 14)).place(relx=0.5, rely=0.5, anchor="center")
            else:
                tk.Label(pane['grid'], text="[ BINDER LOCKED ]", fg=t["accent"], bg=t["bg"], font=("Arial", 14)).place(relx=0.5, rely=0.5, anchor="center"); return
        
        pane_width = pane['canvas'].winfo_width() or 700
        card_w = int((pane_width / cols) - 25); per_page = rows * cols; offset = (page - 1) * per_page
        try: capacity = rows * cols * int(self.b_total_pages.get())
        except: capacity = 9999

        for i in range(per_page):
            idx = offset + i
            r, c = divmod(i, cols)

            border_color = t["accent"]
            is_overflow = is_binder and idx >= capacity
            if is_overflow:
                border_color = t["overflow"]

            slot = tk.Frame(
                pane['grid'],
                bg=t["card_bg"],
                highlightthickness=2,
                highlightbackground=border_color,
                width=card_w,
                height=int(card_w * 1.4) + 85,
            )
            slot.grid(row=r, column=c, padx=5, pady=5)
            slot.grid_propagate(False)
            slot.slot_index = idx
            slot.bind("<B1-Motion>", self.on_drag_motion)
            slot.bind("<ButtonRelease-1>", self.on_drag_release)

            if idx < len(data) and data[idx].get('id') != 'empty':
                card = data[idx]
                logger.info(f"Rendering card at index {idx}: {card['name']} with data {card}")
                
                # Format: Set Name, Card # - Card Name
                s_name = card.get('set_name', 'Unknown Set')
                c_num = card.get('card_number', '?')
                disp_text = f"{s_name}, #{c_num} - {card['name']}"

                tk.Label(
                    slot,
                    text=disp_text,
                    bg=t["card_bg"],
                    fg=t["text"],
                    font=('Arial', 7, 'bold'),
                    wraplength=card_w - 10,
                ).pack(pady=2)
                img_lbl = tk.Label(slot, text="...", bg=t["card_bg"], fg=t["text"])
                img_lbl.pack(expand=True, fill="both")

                for w in [img_lbl, slot]:
                    w.bind("<Button-1>", lambda e, c=card, i=idx, b=is_binder: self.on_drag_start(e, c, i, b))
                    w.bind("<B1-Motion>", self.on_drag_motion)
                    w.bind("<ButtonRelease-1>", self.on_drag_release)
                    if is_binder:
                        w.bind("<Button-3>", lambda e, c=card, i=idx: self.show_binder_context_menu(e, c, i))

                threading.Thread(
                    target=lambda c=card, l=img_lbl, w=card_w - 10, overflow=is_overflow: self.update_label_image(
                        l, self.get_cached_image(c, w, dim=overflow), pane['canvas']
                    ),
                    daemon=True,
                ).start()

                if is_overflow:
                    overlay = tk.Label(
                        slot,
                        text="OVERFLOW",
                        bg="#FF0000",  # Red background for overflow
                        fg="#FFFFFF",
                        font=("Arial", 10, "bold"),
                        wraplength=card_w,
                    )
                    overlay.place(relx=0.5, rely=0.5, anchor="center", relwidth=1.0)

                btn_f = tk.Frame(slot, bg=t["card_bg"])
                btn_f.pack(side="bottom", fill="x", pady=2)
                tk.Button(
                    btn_f,
                    text="X" if is_binder else "Add",
                    command=lambda c=card: self.remove_card_by_object(c) if is_binder else self.quick_add(c),
                    bg="#8B0000" if is_binder else t["btn"],
                    fg="white",
                    font=('Arial', 7),
                ).pack(side="left", fill="x", expand=True)
                search_q = f"{card['name']} {card.get('set_name', '').title()}"
                tk.Button(
                    btn_f,
                    text="Buy",
                    command=lambda q=search_q: webbrowser.open(
                        f"https://www.tcgplayer.com/search/all/product?q={urllib.parse.quote(q)}"
                    ),
                    bg="#2B6CB0",
                    fg="white",
                    font=('Arial', 7),
                ).pack(side="left", fill="x", expand=True)
            else:
                lbl_text = f"Page { (idx // per_page) + 1}\nSlot {idx + 1}"
                if is_overflow:
                    lbl_text += "\n(OVERFLOW)"
                empty = tk.Label(
                    slot,
                    text=lbl_text,
                    font=("Arial", 8),
                    bg=t["card_bg"],
                    fg=t["accent"] if idx < capacity else t["overflow"],
                )
                empty.place(relx=0.5, rely=0.5, anchor="center")
                empty.bind("<B1-Motion>", self.on_drag_motion)
                empty.bind("<ButtonRelease-1>", self.on_drag_release)

        self.update_scroll_region(pane['canvas'])
        self.bind_tree_to_scroll(pane['grid'], pane['canvas'])

    def update_label_image(self, lbl, photo, canvas):
        if photo: 
            self.root.after(0, lambda: lbl.config(image=photo, text=""))
            lbl.image = photo
            self.root.after(100, lambda: self.update_scroll_region(canvas))

    def get_cached_image(self, card, width, dim=False):
        p = os.path.join(CACHE_DIR, f"{card['id']}.jpg")
        if not os.path.exists(p):
            try: 
                logger.debug(f"Downloading image for card: {card['id']}")
                r = requests.get(card['image'], timeout=5); open(p, "wb").write(r.content)
            except Exception as e: 
                logger.error(f"Image download failed for {card['id']}: {e}")
                return None
        
        # Update file timestamp to mark as "recently used"
        try: os.utime(p, None)
        except: pass

        try: 
            img = Image.open(p).resize((width, int(width*1.4)), Image.Resampling.LANCZOS)
            if dim:
                from PIL import ImageEnhance
                enhancer = ImageEnhance.Brightness(img)
                img = enhancer.enhance(0.5)
            return ImageTk.PhotoImage(img)
        except Exception as e:
            logger.error(f"Image processing failed for {p}: {e}")
            return None
    # ==========================================
    # NAVIGATION & PAGINATION
    # ==========================================
    def change_page(self, type_name, delta):
        if type_name == "binder": 
            self.binder_page = max(1, self.binder_page + delta); self.jump_binder_var.set(str(self.binder_page))
            self.refresh_view(target="binder")
        else: 
            self.search_page = max(1, self.search_page + delta); self.jump_search_var.set(str(self.search_page))
            self.refresh_view(target="search")
        

    def go_to_first(self, type_name):
        if type_name == "binder": 
            self.binder_page = 1; self.jump_binder_var.set("1")
            self.refresh_view(target="binder")
        else: 
            self.search_page = 1; self.jump_search_var.set("1")
            self.refresh_view(target="search")

    def go_to_last(self, type_name):
        if type_name == "binder":
            per = int(self.b_rows.get()) * int(self.b_cols.get())
            max_b = (max(len(self.display_owned_cards), per * int(self.b_total_pages.get())) + per - 1) // per
            self.binder_page = max(1, max_b); self.jump_binder_var.set(str(self.binder_page))
            self.refresh_view(target="binder")
        else:
            per = int(self.s_rows.get()) * int(self.s_cols.get()); max_s = (len(self.display_search_data) + per - 1) // per
            self.search_page = max(1, max_s); self.jump_search_var.set(str(self.search_page))
            self.refresh_view(target="search")

    def jump_to_page(self, type_name, event=None):
        try:
            if type_name == "binder": 
                self.binder_page = max(1, int(self.jump_binder_var.get()))
                self.refresh_view(target="binder")
            else: 
                self.search_page = max(1, int(self.jump_search_var.get()))
                self.refresh_view(target="search")
            
        except Exception as e:
            logger.error(f"Invalid page jump: {e}")

    # ==========================================
    # USER & BINDER MANAGEMENT
    # ==========================================
    def select_binder(self, name):
        logger.info(f"Switching binder to: {name}")
        self.current_binder_name = name; self.binder_page = 1; self.jump_binder_var.set("1")
        self.refresh_current_binder_lists(); self.setup_side_menu(); self.refresh_view(target="binder")

    def create_binder(self):
        # Custom Dialog for New Binder
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        
        dialog = tk.Toplevel(self.root)
        dialog.title("New Binder")
        dialog.geometry("300x160")
        dialog.configure(bg=t["bg"])
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Set Icon
        icon_path = resource_path("app.ico")
        if os.path.exists(icon_path):
            dialog.iconbitmap(icon_path)
            
        # Center dialog
        try:
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 150
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 80
            dialog.geometry(f"+{x}+{y}")
        except: pass

        tk.Label(dialog, text="Binder Name:", font=("Segoe UI", 10, "bold"), bg=t["bg"], fg=t["text"]).pack(pady=(20, 5))
        
        name_var = tk.StringVar()
        ent = tk.Entry(dialog, textvariable=name_var, font=("Segoe UI", 10), bg=t["input_bg"], fg=t["input_fg"], 
                       insertbackground=t["input_fg"], relief="flat", highlightthickness=1, highlightbackground=t["frame_fg"])
        ent.pack(fill="x", padx=30, pady=5, ipady=3)
        ent.focus_set()

        def submit(event=None):
            n = name_var.get().strip()
            if not n: return
            
            if n in self.data[self.current_user]["binders"]:
                messagebox.showerror("Error", "Binder name already exists!", parent=dialog)
                return

            logger.info(f"Creating new binder: {n}")
            self.data[self.current_user]["binders"][n] = []
            self.data[self.current_user]["order"].append(n)
            
            # Initialize default layout
            if "binder_layouts" not in self.data[self.current_user]: self.data[self.current_user]["binder_layouts"] = {}
            self.data[self.current_user]["binder_layouts"][n] = {"rows": 3, "cols": 3, "pages": 10}
            
            self.save_all_data(); self.select_binder(n)
            dialog.destroy()

        ent.bind("<Return>", submit)

        btn_frame = tk.Frame(dialog, bg=t["bg"])
        btn_frame.pack(pady=15)
        
        tk.Button(btn_frame, text="Create", command=submit, bg=t["btn_success"], fg="white", font=("Segoe UI", 9, "bold"), 
                  relief="flat", padx=15).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Cancel", command=dialog.destroy, bg=t["btn_danger"], fg="white", font=("Segoe UI", 9), 
                  relief="flat", padx=10).pack(side="left", padx=5)

        self.root.wait_window(dialog)

    def delete_binder(self, name):
        if len(self.data[self.current_user]["binders"]) <= 1: return
        if messagebox.askyesno("Confirm", f"Delete {name}?"):
            logger.warning(f"Deleting binder: {name}")
            del self.data[self.current_user]["binders"][name]
            self.data[self.current_user]["order"].remove(name)
            
            # Remove layout info
            if "binder_layouts" in self.data[self.current_user] and name in self.data[self.current_user]["binder_layouts"]:
                del self.data[self.current_user]["binder_layouts"][name]
                
            if self.current_binder_name == name: self.current_binder_name = self.data[self.current_user]["order"][0]
            self.save_all_data(); self.select_binder(self.current_binder_name)

    def switch_user(self):
        logger.info("Opening Login Dialog")
        self.authenticated = False; self.refresh_view()
        
        # Get current theme colors
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        
        win = tk.Toplevel(self.root)
        win.title("PokeBinder Login")
        
        # Apply App Icon to Login Window
        icon_path = resource_path("app.ico")
        if os.path.exists(icon_path):
            win.iconbitmap(icon_path)

        win.geometry("340x450")
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=t["bg"])
        
        # Center window relative to main app
        try:
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 170
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 225
            win.geometry(f"+{x}+{y}")
        except: pass

        # --- Header Section ---
        tk.Label(win, text="PokeBinder", font=("Segoe UI", 22, "bold"), bg=t["bg"], fg=t["accent"]).pack(pady=(40, 5))
        tk.Label(win, text="User Login", font=("Arial", 10), bg=t["bg"], fg=t["text"]).pack(pady=(0, 30))

        # --- Form Container ---
        form = tk.Frame(win, bg=t["bg"])
        form.pack(fill="x", padx=40)

        # User Selection
        tk.Label(form, text="Select Profile", font=("Arial", 8, "bold"), bg=t["bg"], fg=t["text"]).pack(anchor="w")
        
        u_list = list(self.data.keys())
        u_var = tk.StringVar(value=self.current_user if self.current_user in u_list else (u_list[0] if u_list else ""))
        
        cb = ttk.Combobox(form, textvariable=u_var, values=u_list, state="readonly", font=("Segoe UI", 10))
        cb.pack(fill="x", pady=(2, 15), ipady=3)

        # Password Entry
        tk.Label(form, text="Password", font=("Arial", 8, "bold"), bg=t["bg"], fg=t["text"]).pack(anchor="w")
        
        pw_ent = tk.Entry(form, show="*", bg=t["input_bg"], fg=t["input_fg"], 
                          insertbackground=t["input_fg"], relief="flat", 
                          highlightthickness=1, highlightbackground=t["frame_fg"], font=("Segoe UI", 10))
        pw_ent.pack(fill="x", pady=(2, 5), ipady=5)
        
        # Error Message Label
        err_lbl = tk.Label(form, text="", font=("Arial", 9), bg=t["bg"], fg=t["btn_danger"])
        err_lbl.pack(pady=(0, 15))

        def login(event=None):
            u = u_var.get()
            if u in self.data and self.data[u].get("pw") == pw_ent.get():
                logger.info(f"User {u} authenticated successfully.")
                self.authenticated = True; self.current_user = u; self.binder_page = 1; self.ensure_user_exists()
                
                # Load saved theme preference
                saved_theme = self.data[u].get("dark_mode", True)
                self.dark_mode.set(saved_theme)

                self.refresh_current_binder_lists(); self.setup_side_menu(); self.apply_theme(); self.refresh_view(); win.destroy()
            else:
                logger.warning(f"Failed login attempt for user: {u}")
                err_lbl.config(text="Incorrect password")
                pw_ent.delete(0, "end")
                pw_ent.config(highlightbackground=t["btn_danger"])

        pw_ent.bind("<Return>", login)
        pw_ent.bind("<FocusIn>", lambda e: pw_ent.config(highlightbackground=t["accent"]))

        # --- Buttons ---
        tk.Button(form, text="Login", command=login, bg=t["btn_info"], fg="white", 
                  font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2",
                  activebackground=t["hl"], activeforeground=t["bg"]).pack(fill="x", pady=5, ipady=3)
        
        tk.Button(form, text="Create New Profile", command=lambda: self.create_profile_dialog(win), 
                  bg=t["btn_success"], fg="white", font=("Segoe UI", 9), relief="flat", cursor="hand2",
                  activebackground=t["hl"], activeforeground=t["bg"]).pack(fill="x", pady=5, ipady=2)

    def create_profile_dialog(self, win):
        nu = simpledialog.askstring("New User", "Username:")
        if nu and nu not in self.data:
            np = simpledialog.askstring("Pass", "Password:", show="*")
            logger.info(f"Creating new user profile: {nu}")
            self.data[nu] = {
                "pw": np or "1234", 
                "binders": {"Main Binder": []}, 
                "order": ["Main Binder"],
                "binder_layouts": {"Main Binder": {"rows": 3, "cols": 3, "pages": 10}}
            }
            self.save_all_data(); win.destroy(); self.switch_user()

    # ==========================================
    # API & EXTERNAL DATA LOADERS
    # ==========================================
    def handle_load(self, event=None):
        q = self.set_entry.get().strip()
        self.status_var.set(f"Searching Set: {q}...")
        logger.info(f"API Request: Searching for set '{q}'")
        def fetch():
            try:
                res = requests.get("https://api.tcgdex.net/v2/en/sets").json()
                match = next((s for s in res if q.lower() in s['name'].lower()), None)
                
                if not match:
                    self.status_var.set("Set not found")
                    return

                full = requests.get(f"https://api.tcgdex.net/v2/en/sets/{match['id']}").json()
                self.current_set_name = match['name']
                self.full_set_data = [{'id': c['id'], 'name': c['name'], 'image': f"{c['image']}/low.jpg", 'set_name': self.current_set_name, 'set_id': match['id']} for c in full['cards']]
                self.display_search_data = self.full_set_data.copy()
                self.search_page = 1
                self.jump_search_var.set("1")
                
                logger.info(f"Successfully loaded {len(self.full_set_data)} cards from {self.current_set_name}")
                self.root.after(0, self.refresh_view(target="search"))
                self.root.after(0, lambda: self.status_var.set("Ready"))
            except Exception as e: 
                logger.error(f"Failed to fetch set data: {e}")
                self.status_var.set("Load failed")
        threading.Thread(target=fetch, daemon=True).start()

    def handle_card_search(self, event=None):
        q = self.card_search_entry.get().strip()
        if not q: return
        self.status_var.set(f"Searching Card: {q}...")
        logger.info(f"API Request: Searching for card '{q}'")
        def fetch():
            try:
                # Search for cards by name
                url = f"https://api.tcgdex.net/v2/en/cards?name={urllib.parse.quote(q)}"
                res = requests.get(url).json()
                
                if not res:
                    self.status_var.set("No cards found")
                    return

                # OPTIMIZATION: Load ALL set names once if not cached, 
                # instead of making individual API requests for every card result.
                if not hasattr(self, 'global_set_cache'):
                    try:
                        logger.debug("Fetching global set list for caching...")
                        all_sets = requests.get("https://api.tcgdex.net/v2/en/sets").json()
                        self.global_set_cache = {s['id']: s['name'] for s in all_sets}
                    except: self.global_set_cache = {}

                # Process results
                cards = []
                for c in res:
                    # TCGDex search results usually have id, name, image (base url)
                    if 'image' in c and c['image']:
                        # Filter out TCG Pocket cards (identified by 'tcgp' in image path)
                        if "/tcgp/" in c['image']:
                            continue

                        s_id = c.get('set', {}).get('id')
                        if not s_id and '-' in c['id']:
                            s_id = c['id'].split('-')[0]

                        # Try to get existing set name, or lookup from global cache
                        s_name = c.get('set', {}).get('name')
                        
                        # Use cached name if available and the API gave us a code/missing name
                        if s_id and (not s_name or s_name == s_id):
                            s_name = self.global_set_cache.get(s_id, s_id)

                        cards.append({
                            'id': c['id'],
                            'name': c['name'],
                            'image': f"{c['image']}/low.jpg",
                            'set_name': s_name,
                            'set_id': s_id
                        })
                
                self.current_set_name = f"Search: {q}"
                self.full_set_data = cards
                self.display_search_data = self.full_set_data.copy()
                self.search_page = 1
                self.jump_search_var.set("1")
                
                logger.info(f"Found {len(cards)} cards matching '{q}'")
                self.root.after(0, self.refresh_view(target="search"))
                self.root.after(0, lambda: self.status_var.set("Ready"))
            except Exception as e:
                logger.error(f"Card search failed: {e}")
                self.status_var.set("Search failed")
        threading.Thread(target=fetch, daemon=True).start()

    # ==========================================
    # VIEW UPDATES & FILTERING
    # ==========================================
    def apply_theme(self):
        # Save theme preference if user is logged in
        if self.authenticated and self.current_user in self.data:
            self.data[self.current_user]["dark_mode"] = self.dark_mode.get()
            self.save_all_data()

        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        self.root.configure(bg=t["bg"]); self.menu_frame.configure(bg=t["menu"]); self.top.configure(bg=t["bg"])
        
        # Update Top Bar elements
        self.menu_btn.configure(bg=t["btn"], fg=t["btn_text"], activebackground=t["hl"], activeforeground=t["bg"])
        self.theme_btn.configure(bg=t["btn"], fg=t["text"], selectcolor=t["hl"], activebackground=t["hl"])
        self.status_lbl.configure(bg=t["bg"], fg=t["text"])

        for p in [self.left_pane, self.right_pane]:
            # Update main containers
            for comp in ["frame", "header", "header_tools", "container", "canvas", "grid"]: 
                p[comp].configure(bg=t["bg"])
            
            # Update persistent header children (Title, Filter, Nav controls)
            for child in p['header'].winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(bg=t["bg"], fg=t["text"])
                elif isinstance(child, tk.Entry):
                    child.configure(bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_fg"], highlightbackground=t["frame_fg"])
                elif isinstance(child, tk.Frame): # This is the nav frame
                    child.configure(bg=t["bg"])
                    for nc in child.winfo_children():
                        if isinstance(nc, tk.Label): 
                            nc.configure(bg=t["bg"], fg=t["text"])
                        elif isinstance(nc, tk.Button): 
                            nc.configure(bg=t["btn"], fg=t["btn_text"], activebackground=t["hl"], activeforeground=t["bg"])
                        elif isinstance(nc, tk.Entry): 
                            nc.configure(bg=t["input_bg"], fg=t["input_fg"], insertbackground=t["input_fg"], highlightbackground=t["frame_fg"])
        
        # Rebuild headers and menu to apply new theme colors to buttons and entries
        self.setup_binder_header()
        self.setup_search_header()
        self.setup_side_menu()
        
        self.refresh_view()

    def refresh_view(self, target="both"):
        """
        Refreshes the UI.
        target: "binder", "search", or "both"
        """
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        
        # --- Refresh Binder Side ---
        if target in ["binder", "both"]:
            try:
                pb = int(self.b_rows.get()) * int(self.b_cols.get())
                # Calculate max pages based on content or fixed total pages setting
                max_b = (max(len(self.display_owned_cards), pb * int(self.b_total_pages.get())) + pb - 1) // pb
                self.max_binder_pages_var.set(f"Max: {max(1, max_b)}")
                
                self.render_side(
                    self.left_pane, 
                    self.display_owned_cards, 
                    self.binder_page, 
                    True, 
                    t, 
                    int(self.b_rows.get()), 
                    int(self.b_cols.get())
                )
            except ValueError:
                pass # Handle cases where entry widgets might be empty temporarily

        # --- Refresh Search Side ---
        if target in ["search", "both"]:
            try:
                ps = int(self.s_rows.get()) * int(self.s_cols.get())
                max_s = (len(self.display_search_data) + ps - 1) // ps
                self.max_search_pages_var.set(f"Max: {max(1, max_s)}")
                
                self.render_side(
                    self.right_pane, 
                    self.display_search_data, 
                    self.search_page, 
                    False, 
                    t, 
                    int(self.s_rows.get()), 
                    int(self.s_cols.get())
                )
            except ValueError:
                pass

        self.update_progress()

    def quick_add(self, card): 
        try:
            capacity = int(self.b_rows.get()) * int(self.b_cols.get()) * int(self.b_total_pages.get())
            if len(self.owned_cards) >= capacity:
                if not messagebox.askyesno("Capacity Warning", f"Binder full. Add to digital overflow?"):
                    return
        except: pass
        
        logger.info(f"Quick Add: {card['name']}")
        self.owned_cards.append(card); self.save_all_data(); self.apply_binder_filter(reset_page=False)
        
    def remove_card_by_object(self, card_obj):
        if card_obj in self.owned_cards: 
            logger.info(f"Removing card: {card_obj['name']}")
            self.owned_cards.remove(card_obj); self.save_all_data(); self.apply_binder_filter(reset_page=False)

    def apply_filter(self):
        q = self.filter_var.get().lower().strip()
        
        if not q:
            self.display_search_data = self.full_set_data.copy()
        else:
            # Check if filtering by number (starts with # or is digit)
            is_num_search = q.startswith('#') or q.isdigit()
            
            # Normalize search term: remove '#' and leading zeros
            search_num = q.lstrip('#').lstrip('0') if is_num_search else ""
            if is_num_search and search_num == "": search_num = "0"

            filtered = []
            for c in self.full_set_data:
                if is_num_search:
                    # Ensure card number exists (extract if missing)
                    if 'card_number' not in c:
                        try:
                            if '-' in c['id']: c['card_number'] = c['id'].split('-')[-1]
                            elif 'image' in c:
                                match = re.search(r'/([^/]+)/low\.jpg', c['image'])
                                if match: c['card_number'] = match.group(1)
                            else: c['card_number'] = "0"
                        except: c['card_number'] = "0"

                    # Normalize card number
                    c_num = str(c.get('card_number', '')).lstrip('0')
                    if not c_num: c_num = "0"
                    
                    if c_num == search_num:
                        filtered.append(c)
                else:
                    if q in c['name'].lower():
                        filtered.append(c)
            self.display_search_data = filtered

        self.search_page = 1; self.refresh_view(target="search")

    def apply_binder_filter(self, reset_page=False):
        q = self.binder_filter_var.get().lower().strip()
        
        if not q:
            self.display_owned_cards = self.owned_cards.copy()
        else:
            # Check if filtering by number (starts with # or is digit)
            is_num_search = q.startswith('#') or q.isdigit()
            
            # Normalize search term: remove '#' and leading zeros (e.g. "#023" -> "23")
            search_num = q.lstrip('#').lstrip('0') if is_num_search else ""
            if is_num_search and search_num == "": search_num = "0" # Handle searching for "0"

            filtered = []
            for c in self.owned_cards:
                if is_num_search:
                    # Normalize card number: remove leading zeros
                    c_num = str(c.get('card_number', '')).lstrip('0')
                    if not c_num: c_num = "0"
                    
                    # Exact match on normalized number
                    if c_num == search_num:
                        filtered.append(c)
                else:
                    # Standard name search
                    if q in c['name'].lower():
                        filtered.append(c)
            self.display_owned_cards = filtered

        if reset_page: self.binder_page = 1; self.jump_binder_var.set("1")
        self.refresh_view(target="binder")

    def start_ticker(self, text):
        if self._ticker_job:
            self.root.after_cancel(self._ticker_job)
            self._ticker_job = None
        
        max_len = 28 # Max characters to display
        if len(text) <= max_len:
            self.progress_scroll_var.set(text)
            return

        display_text = text + "   ***   "
        
        def tick(idx):
            s = display_text + display_text
            view = s[idx : idx + max_len]
            self.progress_scroll_var.set(view)
            self._ticker_job = self.root.after(200, lambda: tick((idx + 1) % len(display_text)))
        
        tick(0)

    def update_progress(self):
        if self.current_set_name:
            o = len([c for c in self.owned_cards if c.get('set_name') == self.current_set_name]); t = len(self.full_set_data)
            pct = (o/t)*100 if t else 0
            text = f"{self.current_set_name}: {o}/{t} ({pct:.1f}%)" if t else "No data"
            
            # Dynamic color coding
            if hasattr(self, 'progress_label'):
                t_theme = self.themes["lunar" if self.dark_mode.get() else "solar"]
                if pct == 100: col = t_theme["prog_100"]
                elif pct >= 75: col = t_theme["prog_75"]
                elif pct >= 50: col = t_theme["prog_50"]
                elif pct >= 25: col = t_theme["prog_25"]
                else: col = t_theme["prog_0"]
                self.progress_label.config(fg=col)

            # Only restart ticker if text changes
            if self.progress_text.get() != text:
                self.progress_text.set(text)
                self.start_ticker(text)

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = TCGApp(root)
        root.mainloop()
    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)