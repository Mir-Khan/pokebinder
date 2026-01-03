import os, json, requests, webbrowser, threading, urllib.parse, re, logging
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from PIL import Image, ImageTk

# ==========================================
# LOGGING CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tcg_debug.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Data file for users and binders
SAVE_FILE = "tcg_data.json"
CACHE_DIR = "card_cache"
if not os.path.exists(CACHE_DIR): 
    os.makedirs(CACHE_DIR)
    logger.info(f"Created cache directory: {CACHE_DIR}")

class TCGApp:
    def __init__(self, root):
        logger.info("Initializing TCGApp...")
        self.root = root
        self.root.title("TCG Binder - Multi-User Edition")
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
            "solar": {"bg": "#FFFBE6", "fg": "#5C4033", "accent": "#FFA500", "card_bg": "#FFFFFF", "btn": "#FFD700", "hl": "#FFD700", "owned": "#4CAF50", "text": "#000000", "menu": "#F0EAD6", "overflow": "#8B4513"},
            "lunar": {"bg": "#1A1A2E", "fg": "#E0E0E0", "accent": "#4B0082", "card_bg": "#16213E", "btn": "#3E4A89", "hl": "#FFD700", "owned": "#2E7D32", "text": "#FFFFFF", "menu": "#0F3460", "overflow": "#450000"}
        }
        
        self.b_rows, self.b_cols = tk.StringVar(value="3"), tk.StringVar(value="3")
        self.b_total_pages = tk.StringVar(value="10")
        self.s_rows, self.s_cols = tk.StringVar(value="4"), tk.StringVar(value="4")
        
        self.jump_search_var = tk.StringVar(value="1")
        self.jump_binder_var = tk.StringVar(value="1")
        self.max_search_pages_var = tk.StringVar(value="Max: 1")
        self.max_binder_pages_var = tk.StringVar(value="Max: 1")
        
        self.binder_title_var = tk.StringVar(value=self.current_binder_name.upper())
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *args: self.apply_filter())
        self.binder_filter_var = tk.StringVar()
        self.binder_filter_var.trace_add("write", lambda *args: self.apply_binder_filter(reset_page=True))
        
        self.status_var = tk.StringVar(value="Ready")
        self.progress_text = tk.StringVar(value="No set loaded")
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
        logger.info("UI Setup complete.")

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
            if rows <= 0 or cols <= 0:
                raise ValueError("Rows and columns must be positive integers.")
            
            logger.info(f"Applying binder grid: {rows} rows x {cols} cols")
            
            # Re-render the current page with the updated grid
            self.refresh_view()
        except ValueError as e:
            logger.error(f"Invalid grid size: {e}")
            messagebox.showerror("Invalid Input", "Rows and columns must be positive integers.")



    def sort_binder(self):
        logger.info(f"Sorting binder: {self.current_binder_name}")
        self.owned_cards = [c for c in self.owned_cards if c.get('id') != 'empty']
        self.owned_cards.sort(key=lambda x: x['name'].lower())
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
        per_page = int(self.b_rows.get()) * int(self.b_cols.get())
        
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
            self.data["DefaultUser"] = {"pw": "1234", "binders": {"Main Binder": []}, "order": ["Main Binder"]}
        if self.current_user not in self.data:
            self.current_user = list(self.data.keys())[0]
        user_data = self.data[self.current_user]
        if "order" not in user_data: user_data["order"] = list(user_data["binders"].keys())
        if self.current_binder_name not in user_data["binders"]:
            self.current_binder_name = user_data["order"][0]

    def refresh_current_binder_lists(self):
        self.owned_cards = self.data[self.current_user]["binders"][self.current_binder_name]
        self.display_owned_cards = self.owned_cards.copy()
        self.binder_title_var.set(self.current_binder_name.upper())

    # ==========================================
    # UI CONSTRUCTION
    # ==========================================
    def setup_ui(self):
        self.main_container = tk.Frame(self.root)
        self.main_container.pack(fill="both", expand=True)

        self.menu_frame = tk.Frame(self.main_container, width=220)
        self.menu_frame.pack(side="left", fill="y")
        self.setup_side_menu()

        self.content_frame = tk.Frame(self.main_container)
        self.content_frame.pack(side="right", fill="both", expand=True)

        self.top = tk.Frame(self.content_frame, pady=5)
        self.top.pack(fill="x", side="top")
        
        tk.Button(self.top, text="☰", font=("Arial", 11, "bold"), command=self.toggle_menu, relief="flat").pack(side="left", padx=10)
        tk.Checkbutton(self.top, text="🌙 Theme", variable=self.dark_mode, command=self.apply_theme, indicatoron=False).pack(side="right", padx=10)
        tk.Label(self.top, textvariable=self.status_var, font=("Arial", 9, "italic")).pack(side="right", padx=20)
        
        self.paned = tk.PanedWindow(self.content_frame, orient="horizontal", sashwidth=4, bg="#333333"); self.paned.pack(fill="both", expand=True)
        
        self.left_pane = self.create_scrollable_pane(self.paned, self.binder_title_var, "binder")
        self.right_pane = self.create_scrollable_pane(self.paned, tk.StringVar(value="SET SEARCH"), "search")
        
        self.setup_binder_header()
        self.setup_search_header()

    def setup_binder_header(self):
        h = self.left_pane['header_tools']
        for w in h.winfo_children(): w.destroy()
        g_f = tk.Frame(h); g_f.pack(side="left", padx=5)
        tk.Label(g_f, text="Binder Grid Size:", font=("Arial", 8)).pack(side="left")
        ttk.Entry(g_f, width=2, textvariable=self.b_rows).pack(side="left")
        tk.Label(g_f, text="x", font=("Arial", 8)).pack(side="left")
        ttk.Entry(g_f, width=2, textvariable=self.b_cols).pack(side="left")
        tk.Label(g_f, text=" Pgs:", font=("Arial", 8)).pack(side="left")
        ttk.Entry(g_f, width=3, textvariable=self.b_total_pages).pack(side="left")
        
        tk.Button(h, text="Apply Grid", command=self.apply_binder_grid, bg="#2bb532", fg="white", font=("Arial", 8), padx=5).pack(side="left", padx=2)
        tk.Button(h, text="Sort", command=self.sort_binder, bg="#555", fg="white", font=("Arial", 8), padx=5).pack(side="left", padx=2)
        tk.Button(h, text="Empty", command=self.clear_binder, bg="#8B0000", fg="white", font=("Arial", 8), padx=5).pack(side="left", padx=2)
        tk.Button(h, text="+Full", command=self.add_full_set_to_binder, bg="#2E7D32", fg="white", font=("Arial", 8), padx=5).pack(side="left", padx=2)
        tk.Button(h, text="Set", command=self.refresh_view, bg="#3E4A89", fg="white", font=("Arial", 8), padx=5).pack(side="left", padx=2)

    def setup_search_header(self):
        h = self.right_pane['header_tools']
        for w in h.winfo_children(): w.destroy()
        g_f = tk.Frame(h); g_f.pack(side="left", padx=5)
        tk.Label(g_f, text="Grid:", font=("Arial", 8)).pack(side="left")
        ttk.Entry(g_f, width=2, textvariable=self.s_rows).pack(side="left")
        tk.Label(g_f, text="x", font=("Arial", 8)).pack(side="left")
        ttk.Entry(g_f, width=2, textvariable=self.s_cols).pack(side="left")
        tk.Button(g_f, text="Set", command=self.refresh_view, font=("Arial", 8), padx=3).pack(side="left", padx=2)
        l_f = tk.Frame(h); l_f.pack(side="left", padx=5)
        self.set_entry = ttk.Entry(l_f, width=12); self.set_entry.insert(0, "Surging Sparks"); self.set_entry.pack(side="left")
        self.set_entry.bind("<Return>", self.handle_load)
        tk.Button(l_f, text="Load", command=self.handle_load, bg="#3E4A89", fg="white", font=("Arial", 8)).pack(side="left", padx=2)
        tk.Label(h, textvariable=self.progress_text, font=("Arial", 8, "bold"), fg="#4CAF50").pack(side="right", padx=10)

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
        frame = tk.Frame(parent); parent.add(frame, stretch="always")
        header = tk.Frame(frame); header.pack(fill="x", pady=2)
        tk.Label(header, textvariable=title_var, font=('Segoe UI', 10, 'bold')).pack(side="left", padx=10)
        ttk.Entry(header, width=10, textvariable=self.binder_filter_var if type_name == "binder" else self.filter_var).pack(side="left", padx=2)
        
        nav = tk.Frame(header); nav.pack(side="right", padx=10)
        tk.Label(nav, textvariable=self.max_binder_pages_var if type_name == "binder" else self.max_search_pages_var, font=("Arial", 8)).pack(side="left", padx=5)
        tk.Button(nav, text="|<<", command=lambda: self.go_to_first(type_name), font=("Arial", 8)).pack(side="left", padx=1)
        tk.Button(nav, text="<", command=lambda: self.change_page(type_name, -1), font=("Arial", 8)).pack(side="left", padx=1)
        ent = tk.Entry(nav, width=3, textvariable=self.jump_binder_var if type_name == "binder" else self.jump_search_var)
        ent.pack(side="left", padx=2); ent.bind("<Return>", lambda e: self.jump_to_page(type_name, e))
        tk.Button(nav, text=">", command=lambda: self.change_page(type_name, 1), font=("Arial", 8)).pack(side="left", padx=1)
        tk.Button(nav, text=">>|", command=lambda: self.go_to_last(type_name), font=("Arial", 8)).pack(side="left", padx=1)
        
        tools_row = tk.Frame(frame); tools_row.pack(fill="x", pady=2)
        container = tk.Frame(frame); container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0)
        v_scroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        grid = tk.Frame(canvas); canvas.create_window((0, 0), window=grid, anchor="nw")
        canvas.configure(yscrollcommand=v_scroll.set)
        canvas.pack(side="left", fill="both", expand=True); v_scroll.pack(side="right", fill="y")
        return {"grid": grid, "canvas": canvas, "frame": frame, "header": header, "header_tools": tools_row, "container": container}

    # ==========================================
    # RENDERING & IMAGE CACHING
    # ==========================================
    def render_side(self, pane, data, page, is_binder, t, rows, cols):
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
                tk.Label(
                    slot,
                    text=card['name'],
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
        if type_name == "binder": self.binder_page = max(1, self.binder_page + delta); self.jump_binder_var.set(str(self.binder_page))
        else: self.search_page = max(1, self.search_page + delta); self.jump_search_var.set(str(self.search_page))
        self.refresh_view()

    def go_to_first(self, type_name):
        if type_name == "binder": self.binder_page = 1; self.jump_binder_var.set("1")
        else: self.search_page = 1; self.jump_search_var.set("1")
        self.refresh_view()

    def go_to_last(self, type_name):
        if type_name == "binder":
            per = int(self.b_rows.get()) * int(self.b_cols.get())
            max_b = (max(len(self.display_owned_cards), per * int(self.b_total_pages.get())) + per - 1) // per
            self.binder_page = max(1, max_b); self.jump_binder_var.set(str(self.binder_page))
        else:
            per = int(self.s_rows.get()) * int(self.s_cols.get()); max_s = (len(self.display_search_data) + per - 1) // per
            self.search_page = max(1, max_s); self.jump_search_var.set(str(self.search_page))
        self.refresh_view()

    def jump_to_page(self, type_name, event=None):
        try:
            if type_name == "binder": self.binder_page = max(1, int(self.jump_binder_var.get()))
            else: self.search_page = max(1, int(self.jump_search_var.get()))
            self.refresh_view()
        except Exception as e:
            logger.error(f"Invalid page jump: {e}")

    # ==========================================
    # USER & BINDER MANAGEMENT
    # ==========================================
    def select_binder(self, name):
        logger.info(f"Switching binder to: {name}")
        self.current_binder_name = name; self.binder_page = 1; self.jump_binder_var.set("1")
        self.refresh_current_binder_lists(); self.setup_side_menu(); self.refresh_view()

    def create_binder(self):
        n = simpledialog.askstring("New", "Name:")
        if n and n not in self.data[self.current_user]["binders"]:
            logger.info(f"Creating new binder: {n}")
            self.data[self.current_user]["binders"][n] = []; self.data[self.current_user]["order"].append(n)
            self.save_all_data(); self.select_binder(n)

    def delete_binder(self, name):
        if len(self.data[self.current_user]["binders"]) <= 1: return
        if messagebox.askyesno("Confirm", f"Delete {name}?"):
            logger.warning(f"Deleting binder: {name}")
            del self.data[self.current_user]["binders"][name]; self.data[self.current_user]["order"].remove(name)
            if self.current_binder_name == name: self.current_binder_name = self.data[self.current_user]["order"][0]
            self.save_all_data(); self.select_binder(self.current_binder_name)

    def switch_user(self):
        logger.info("Opening Login Dialog")
        self.authenticated = False; self.refresh_view()
        win = tk.Toplevel(self.root); win.title("Switch User"); win.geometry("350x400"); win.transient(self.root); win.grab_set()
        u_list = list(self.data.keys()); u_var = tk.StringVar(value=self.current_user if self.current_user in u_list else (u_list[0] if u_list else ""))
        ttk.Combobox(win, textvariable=u_var, values=u_list, state="readonly").pack(pady=5)
        pw_ent = tk.Entry(win, show="*"); pw_ent.pack(pady=5)
        def login():
            u = u_var.get()
            if u in self.data and self.data[u].get("pw") == pw_ent.get():
                logger.info(f"User {u} authenticated successfully.")
                self.authenticated = True; self.current_user = u; self.binder_page = 1; self.ensure_user_exists()
                self.refresh_current_binder_lists(); self.setup_side_menu(); self.apply_theme(); self.refresh_view(); win.destroy()
            else:
                logger.warning(f"Failed login attempt for user: {u}")
        tk.Button(win, text="Login", bg="#3E4A89", fg="white", width=15, command=login).pack(pady=10)
        tk.Button(win, text="Create Profile", bg="#2E7D32", fg="white", width=15, command=lambda: self.create_profile_dialog(win)).pack()

    def create_profile_dialog(self, win):
        nu = simpledialog.askstring("New User", "Username:")
        if nu and nu not in self.data:
            np = simpledialog.askstring("Pass", "Password:", show="*")
            logger.info(f"Creating new user profile: {nu}")
            self.data[nu] = {"pw": np or "1234", "binders": {"Main Binder": []}, "order": ["Main Binder"]}
            self.save_all_data(); win.destroy(); self.switch_user()

    # ==========================================
    # API & EXTERNAL DATA LOADERS
    # ==========================================
    def handle_load(self, event=None):
        q = self.set_entry.get().strip()
        self.status_var.set(f"Searching {q}...")
        logger.info(f"API Request: Searching for set '{q}'")
        def fetch():
            try:
                res = requests.get("https://api.tcgdex.net/v2/en/sets").json()
                match = next(s for s in res if q.lower() in s['name'].lower())
                full = requests.get(f"https://api.tcgdex.net/v2/en/sets/{match['id']}").json()
                self.current_set_name = match['name']
                self.full_set_data = [{'id': c['id'], 'name': c['name'], 'image': f"{c['image']}/low.jpg", 'set_name': self.current_set_name, 'set_id': match['id']} for c in full['cards']]
                self.display_search_data = self.full_set_data.copy()
                logger.info(f"Successfully loaded {len(self.full_set_data)} cards from {self.current_set_name}")
                self.root.after(0, self.refresh_view)  # Replace reset_and_refresh with refresh_view
            except Exception as e: 
                logger.error(f"Failed to fetch set data: {e}")
                self.status_var.set("Load failed")
        threading.Thread(target=fetch, daemon=True).start()

    # ==========================================
    # VIEW UPDATES & FILTERING
    # ==========================================
    def apply_theme(self):
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        self.root.configure(bg=t["bg"]); self.menu_frame.configure(bg=t["menu"]); self.top.configure(bg=t["bg"])
        for p in [self.left_pane, self.right_pane]:
            for comp in ["frame", "header", "header_tools", "container", "canvas", "grid"]: p[comp].configure(bg=t["bg"])
        self.refresh_view()

    def refresh_view(self):
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        ps = int(self.s_rows.get()) * int(self.s_cols.get()); max_s = (len(self.display_search_data) + ps - 1) // ps
        self.max_search_pages_var.set(f"Max: {max(1, max_s)}")
        pb = int(self.b_rows.get()) * int(self.b_cols.get()); max_b = (max(len(self.display_owned_cards), pb * int(self.b_total_pages.get())) + pb - 1) // pb
        self.max_binder_pages_var.set(f"Max: {max(1, max_b)}")
        self.render_side(self.left_pane, self.display_owned_cards, self.binder_page, True, t, int(self.b_rows.get()), int(self.b_cols.get()))
        self.render_side(self.right_pane, self.display_search_data, self.search_page, False, t, int(self.s_rows.get()), int(self.s_cols.get()))
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
        q = self.filter_var.get().lower(); self.display_search_data = [c for c in self.full_set_data if q in c['name'].lower()] if q else self.full_set_data.copy()
        self.search_page = 1; self.refresh_view()

    def apply_binder_filter(self, reset_page=False):
        q = self.binder_filter_var.get().lower(); self.display_owned_cards = [c for c in self.owned_cards if q in c['name'].lower()] if q else self.owned_cards.copy()
        if reset_page: self.binder_page = 1; self.jump_binder_var.set("1")
        self.refresh_view()

    def update_progress(self):
        if self.current_set_name:
            o = len([c for c in self.owned_cards if c.get('set_name') == self.current_set_name]); t = len(self.full_set_data)
            self.progress_text.set(f"{self.current_set_name}: {o}/{t} ({(o/t)*100:.1f}%)" if t else "No data")

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = TCGApp(root)
        root.mainloop()
    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)