import os, json, requests, webbrowser, tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from io import BytesIO
import threading

SAVE_FILE = "my_collection.json"

class TCGApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TCG Binder - Solar & Lunar")
        self.root.geometry("1100x850") 
        
        # --- Theme State ---
        self.dark_mode = tk.BooleanVar(value=True)
        self.themes = {
            "solar": {
                "bg": "#FFFBE6", "fg": "#5C4033", "accent": "#FFA500", 
                "card_bg": "#FFFFFF", "btn": "#FFD700", "label": "Solar Mode"
            },
            "lunar": {
                "bg": "#1A1A2E", "fg": "#E0E0E0", "accent": "#4B0082", 
                "card_bg": "#16213E", "btn": "#0F3460", "label": "Lunar Mode"
            }
        }
        
        # --- UI Variables ---
        self.sheets_var = tk.StringVar(value="10") 
        self.row_var = tk.StringVar(value="3")
        self.col_var = tk.StringVar(value="3")
        self.search_var = tk.StringVar()
        self.missing_only_var = tk.BooleanVar(value=False) # NEW: Missing filter state
        self.page_selection = tk.StringVar()
        self.manual_code_var = tk.StringVar()
        self.status_var = tk.StringVar()
        
        # Initial capacity calculation to prevent crash
        self.total_capacity = int(self.sheets_var.get()) * int(self.row_var.get()) * int(self.col_var.get())
        
        # --- State ---
        self.card_data = []      
        self.filtered_data = []  
        self.owned_cards = self.load_collection()
        self.selected_to_buy = set()
        self.current_page = 1
        self.raw_images = {}
        self.official_codes_map = {} 

        self.setup_ui()
        self.apply_theme() 
        self.apply_live_config()
        
        # Observers for real-time filtering
        self.search_var.trace_add("write", lambda *args: self.apply_filter())
        
        threading.Thread(target=self.fetch_official_codes, daemon=True).start()

    def load_collection(self):
        if os.path.exists(SAVE_FILE):
            try:
                with open(SAVE_FILE, 'r') as f: return set(json.load(f))
            except: return set()
        return set()

    def apply_theme(self):
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        self.root.configure(bg=t["bg"])
        
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background=t["bg"])
        style.configure("TLabelframe", background=t["bg"], foreground=t["fg"])
        style.configure("TLabelframe.Label", background=t["bg"], foreground=t["fg"], font=('Segoe UI', 10, 'bold'))
        style.configure("TLabel", background=t["bg"], foreground=t["fg"])
        style.configure("TCheckbutton", background=t["bg"], foreground=t["fg"])
        style.configure("TButton", background=t["btn"], foreground="white", borderwidth=0)
        style.map("TButton", background=[('active', t["accent"])])
        
        self.status_lbl.config(bg=t["btn"], fg="white")
        self.update_stats()
        self.refresh_binder()

    def setup_ui(self):
        self.top = ttk.Frame(self.root, padding=10)
        self.top.pack(fill="x", side="top")
        
        # 1. Config
        layout_cfg = ttk.LabelFrame(self.top, text="Binder Config")
        layout_cfg.pack(side="left", padx=5)
        ttk.Entry(layout_cfg, width=3, textvariable=self.sheets_var).pack(side="left", padx=2)
        ttk.Label(layout_cfg, text="x").pack(side="left")
        ttk.Entry(layout_cfg, width=2, textvariable=self.row_var).pack(side="left")
        ttk.Label(layout_cfg, text="x").pack(side="left")
        ttk.Entry(layout_cfg, width=2, textvariable=self.col_var).pack(side="left")
        ttk.Button(layout_cfg, text="Apply", width=6, command=self.apply_live_config).pack(side="left", padx=5)

        # 2. Load
        search_set = ttk.LabelFrame(self.top, text="Load Set")
        search_set.pack(side="left", padx=5)
        self.set_entry = ttk.Entry(search_set, width=12)
        self.set_entry.insert(0, "Silver Tempest")
        self.set_entry.pack(side="left", padx=2)
        ttk.Button(search_set, text="Go", command=self.handle_load).pack(side="left")

        # 3. Filters (Search + Missing Toggle)
        filter_frame = ttk.LabelFrame(self.top, text="Filters")
        filter_frame.pack(side="left", padx=5)
        ttk.Entry(filter_frame, textvariable=self.search_var, width=12).pack(side="left", padx=5)
        tk.Checkbutton(filter_frame, text="Missing Only", variable=self.missing_only_var, 
                       command=self.apply_filter, bg=self.themes["lunar"]["bg"] if self.dark_mode.get() else self.themes["solar"]["bg"],
                       fg="white" if self.dark_mode.get() else "black", activebackground="#4B0082").pack(side="left", padx=2)

        # 4. Mass Entry
        buy_tools = ttk.LabelFrame(self.top, text="Mass Actions")
        buy_tools.pack(side="left", padx=5)
        ttk.Button(buy_tools, text="Copy Selected", command=lambda: self.generate_entry("selected")).pack(side="left", padx=2)
        ttk.Button(buy_tools, text="Copy Missing", command=lambda: self.generate_entry("all")).pack(side="left", padx=2)

        # Theme Toggle
        theme_btn = tk.Checkbutton(self.top, text="🌙 Night Theme", variable=self.dark_mode, 
                                   command=self.apply_theme, onvalue=True, offvalue=False,
                                   bg="#4B0082", fg="white", selectcolor="#1A1A2E", indicatoron=False, padx=10)
        theme_btn.pack(side="right", padx=10)

        # Navigation
        self.nav_bar = ttk.Frame(self.root, padding=10)
        self.nav_bar.pack(fill="x", side="bottom")
        ttk.Button(self.nav_bar, text="<<<", width=5, command=self.prev_page).pack(side="left")
        
        nav_group = ttk.Frame(self.nav_bar)
        nav_group.pack(side="left", expand=True)
        self.page_dropdown = ttk.Combobox(nav_group, textvariable=self.page_selection, state="readonly", width=25)
        self.page_dropdown.pack(side="left", padx=5)
        self.page_dropdown.bind("<<ComboboxSelected>>", self.on_page_select)
        self.total_pages_lbl = ttk.Label(nav_group, text="of 0") 
        self.total_pages_lbl.pack(side="left")
        
        self.progress_lbl = ttk.Label(self.nav_bar, text="0/0")
        self.progress_lbl.pack(side="left", padx=10)
        ttk.Button(self.nav_bar, text=">>>", width=5, command=self.next_page).pack(side="right")

        self.status_lbl = tk.Label(self.root, textvariable=self.status_var, relief="flat", anchor="w", font=('Arial', 9))
        self.status_lbl.pack(side="bottom", fill="x")

        # Scrollable Area
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=10, pady=5)
        self.canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.binder_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.binder_frame, anchor="nw")
        self.binder_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def fetch_official_codes(self):
        try:
            res = requests.get("https://api.pokemontcg.io/v2/sets").json()
            for s in res['data']:
                code = s.get('ptcgoCode') or s.get('id').upper()
                self.official_codes_map[s['name'].lower()] = code
        except: pass

    def handle_load(self):
        query = self.set_entry.get().strip()
        try:
            res = requests.get("https://api.tcgdex.net/v2/en/sets").json()
            match = next(s for s in res if query.lower() in s['name'].lower())
            found_code = self.official_codes_map.get(match['name'].lower())
            self.manual_code_var.set(found_code if found_code else match['id'].upper())
            full_set = requests.get(f"https://api.tcgdex.net/v2/en/sets/{match['id']}").json()
            self.card_data = [{'id': c['id'], 'num': c['localId'], 'name': c['name'], 'image': f"{c['image']}/low.jpg"} for c in full_set['cards']]
            self.current_page = 1
            self.raw_images.clear()
            self.apply_filter()
        except: self.status_var.set("❌ Set not found.")

    def apply_filter(self):
        term = self.search_var.get().lower()
        show_missing_only = self.missing_only_var.get()
        
        self.filtered_data = []
        for c in self.card_data:
            match_search = term in c['name'].lower()
            match_missing = (c['id'] not in self.owned_cards) if show_missing_only else True
            
            if match_search and match_missing:
                self.filtered_data.append(c)
                
        self.current_page = 1
        self.apply_live_config()

    def apply_live_config(self):
        try:
            self.slots_per_page = int(self.row_var.get()) * int(self.col_var.get())
            self.total_capacity = int(self.sheets_var.get()) * self.slots_per_page
            cols = int(self.col_var.get())
            for i in range(cols): self.binder_frame.grid_columnconfigure(i, weight=1)

            if self.filtered_data:
                total_cards = len(self.filtered_data)
                max_pages = (total_cards + self.slots_per_page - 1) // self.slots_per_page
                if self.current_page > max_pages: self.current_page = 1
                self.update_navigation_options()
                self.refresh_binder()
                self.update_stats()
            else:
                for w in self.binder_frame.winfo_children(): w.destroy()
                self.update_stats()
        except: pass

    def refresh_binder(self):
        for w in self.binder_frame.winfo_children(): w.destroy()
        if not self.filtered_data: return
        
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        self.canvas.config(bg=t["bg"])
        self.binder_frame.config(style="TFrame")

        offset = (self.current_page - 1) * self.slots_per_page
        cols = int(self.col_var.get())
        canvas_width = self.canvas.winfo_width() if self.canvas.winfo_width() > 100 else 1000
        target_img_width = int((canvas_width / cols) * 0.75)
        target_img_height = int(target_img_width * 1.4)

        for i in range(self.slots_per_page):
            idx = offset + i
            if idx >= len(self.filtered_data): break
            r, c = divmod(i, cols)
            
            # Maintain capacity check relative to full set
            original_idx = next((i for i, item in enumerate(self.card_data) if item["id"] == self.filtered_data[idx]["id"]), 0)
            fits = original_idx < self.total_capacity
            
            slot = tk.Frame(self.binder_frame, bg=t["card_bg"], highlightbackground=t["accent"], highlightthickness=1)
            slot.grid(row=r, column=c, padx=8, pady=8, sticky="nsew")
            
            card = self.filtered_data[idx]
            if card['id'] in self.raw_images:
                photo = self.scale_image(self.raw_images[card['id']], target_img_width, target_img_height)
                self.render_card_ui(slot, photo, card, fits, t)
            else: 
                threading.Thread(target=self.load_image_to_slot, args=(slot, card, fits, target_img_width, target_img_height, t), daemon=True).start()

    def scale_image(self, pil_img, w, h):
        resized = pil_img.resize((w, h), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(resized)

    def load_image_to_slot(self, frame, card, fits, w, h, t):
        try:
            res = requests.get(card['image'], timeout=10)
            pil_img = Image.open(BytesIO(res.content))
            self.raw_images[card['id']] = pil_img
            photo = self.scale_image(pil_img, w, h)
            self.root.after(0, lambda: self.render_card_ui(frame, photo, card, fits, t))
        except: pass

    def render_card_ui(self, frame, photo, card, fits, t):
        for w in frame.winfo_children(): w.destroy()
        lbl = tk.Label(frame, image=photo, bg=t["card_bg"])
        lbl.image = photo 
        lbl.pack(pady=5)
        
        info_color = t["fg"] if fits else "red"
        txt = f"#{card['num']} - {card['name']}" if fits else "BEYOND CAPACITY"
        tk.Label(frame, text=txt, fg=info_color, bg=t["card_bg"], font=('Segoe UI', 9, 'bold')).pack()
        
        btn_f = tk.Frame(frame, bg=t["card_bg"])
        btn_f.pack(pady=2)
        o_var = tk.BooleanVar(value=card['id'] in self.owned_cards)
        tk.Checkbutton(btn_f, text="Own", variable=o_var, command=lambda: self.toggle_owned(card['id'], o_var.get()),
                       bg=t["card_bg"], fg=t["fg"], selectcolor=t["bg"], activebackground=t["card_bg"]).grid(row=0, column=0, padx=5)
        
        b_var = tk.BooleanVar(value=card['id'] in self.selected_to_buy)
        tk.Checkbutton(btn_f, text="List", variable=b_var, command=lambda: self.toggle_buy(card['id'], b_var.get()),
                       bg=t["card_bg"], fg=t["fg"], selectcolor=t["bg"], activebackground=t["card_bg"]).grid(row=0, column=1, padx=5)

        tk.Button(frame, text="Buy Single", command=lambda: self.buy_single(card['name']), 
                  bg=t["btn"], fg="white", relief="flat", font=('Arial', 8)).pack(fill="x", padx=20, pady=5)

    def update_navigation_options(self):
        total_cards = len(self.filtered_data)
        num_pages = (total_cards + self.slots_per_page - 1) // self.slots_per_page
        self.total_pages_lbl.config(text=f"of {num_pages}")
        self.page_dropdown['values'] = [f"Page {p}" for p in range(1, num_pages + 1)]
        if self.page_dropdown['values']: self.page_dropdown.current(min(self.current_page - 1, len(self.page_dropdown['values'])-1))

    def on_page_select(self, event):
        self.current_page = self.page_dropdown.current() + 1
        self.refresh_binder()

    def update_stats(self):
        owned = sum(1 for c in self.card_data if c['id'] in self.owned_cards)
        total = len(self.card_data)
        self.progress_lbl.config(text=f"Progress: {owned}/{total}")
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        self.status_var.set(f"Theme: {t['label']} | Binder Capacity: {self.total_capacity} slots")

    def toggle_owned(self, cid, val):
        if val: self.owned_cards.add(cid)
        else: self.owned_cards.discard(cid)
        with open(SAVE_FILE, 'w') as f: json.dump(list(self.owned_cards), f)
        self.update_stats()
        if self.missing_only_var.get(): self.apply_filter()

    def toggle_buy(self, cid, val):
        if val: self.selected_to_buy.add(cid)
        else: self.selected_to_buy.discard(cid)

    def buy_single(self, card_name):
        clean_name = card_name.replace("é", "e").replace(" ", "+")
        set_name = self.set_entry.get().replace(" ", "+")
        webbrowser.open(f"https://www.tcgplayer.com/search/pokemon/product?q={clean_name}+{set_name}")

    def generate_entry(self, mode):
        target_ids = self.selected_to_buy if mode == "selected" else [c['id'] for c in self.card_data if c['id'] not in self.owned_cards]
        set_code = self.manual_code_var.get().strip().upper()
        list_text = "".join([f"1 {c['name'].replace('é', 'e')} [{set_code}]\n" for c in self.card_data if c['id'] in target_ids])
        self.root.clipboard_clear(); self.root.clipboard_append(list_text)
        webbrowser.open("https://www.tcgplayer.com/massentry")

    def prev_page(self): 
        if self.current_page > 1: self.current_page -= 1; self.refresh_binder()
    def next_page(self): 
        if (self.current_page * self.slots_per_page) < len(self.filtered_data): self.current_page += 1; self.refresh_binder()

if __name__ == "__main__":
    root = tk.Tk(); app = TCGApp(root); root.mainloop()