import os, json, requests, webbrowser, threading, urllib.parse, re
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

SAVE_FILE = "my_collection.json"
CACHE_DIR = "card_cache"
if not os.path.exists(CACHE_DIR): os.makedirs(CACHE_DIR)

class TCGApp:
    def __init__(self, root):
        self.root = root
        self.root.title("TCG Binder - Interactive Edition")
        self.root.geometry("1500x900") 
        
        self.dark_mode = tk.BooleanVar(value=True)
        self.themes = {
            "solar": {"bg": "#FFFBE6", "fg": "#5C4033", "accent": "#FFA500", "card_bg": "#FFFFFF", "btn": "#FFD700", "hl": "#FFD700", "owned": "#4CAF50", "text": "#000000"},
            "lunar": {"bg": "#1A1A2E", "fg": "#E0E0E0", "accent": "#4B0082", "card_bg": "#16213E", "btn": "#3E4A89", "hl": "#FFD700", "owned": "#2E7D32", "text": "#FFFFFF"}
        }
        
        self.b_rows, self.b_cols = tk.StringVar(value="3"), tk.StringVar(value="3")
        self.b_total_pages = tk.StringVar(value="10")
        self.s_rows, self.s_cols = tk.StringVar(value="4"), tk.StringVar(value="4")
        
        self.jump_search_var = tk.StringVar(value="1")
        self.jump_binder_var = tk.StringVar(value="1")
        self.max_search_pages_var = tk.StringVar(value="Max: 1")
        self.max_binder_pages_var = tk.StringVar(value="Max: 1")
        
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *args: self.apply_filter())
        
        self.binder_filter_var = tk.StringVar()
        self.binder_filter_var.trace_add("write", lambda *args: self.apply_binder_filter())
        
        self.status_var = tk.StringVar(value="Ready")
        self.progress_text = tk.StringVar(value="Load a set...")
        self.binder_page, self.search_page = 1, 1
        
        self.full_set_data = [] 
        self.display_search_data = [] 
        self.owned_cards = self.load_collection()
        self.display_owned_cards = self.owned_cards.copy()
        self.current_set_name = ""
        
        self.setup_ui()
        self.apply_theme()
        self.root.after(100, self.refresh_view)

    def load_collection(self):
        if os.path.exists(SAVE_FILE):
            try:
                with open(SAVE_FILE, 'r') as f: return json.load(f)
            except: return []
        return []

    def save_collection(self):
        with open(SAVE_FILE, 'w') as f: json.dump(self.owned_cards, f)

    def handle_load(self, event=None):
        query = self.set_entry.get().strip()
        def fetch():
            try:
                self.status_var.set(f"Searching for '{query}'...")
                res = requests.get("https://api.tcgdex.net/v2/en/sets").json()
                match = next(s for s in res if query.lower() in s['name'].lower())
                full = requests.get(f"https://api.tcgdex.net/v2/en/sets/{match['id']}").json()
                self.current_set_name = match['name']
                self.full_set_data = [{'id': c['id'], 'name': c['name'], 'image': f"{c['image']}/low.jpg", 'set_name': self.current_set_name, 'set_id': match['id']} for c in full['cards']]
                self.display_search_data = self.full_set_data.copy()
                self.root.after(0, self.reset_and_refresh)
                self.status_var.set(f"Loaded {self.current_set_name}")
            except Exception as e: self.status_var.set(f"❌ Error: {str(e)}")
        threading.Thread(target=fetch, daemon=True).start()

    def setup_ui(self):
        self.top = tk.Frame(self.root, pady=10); self.top.pack(fill="x", side="top")
        
        # --- Binder Config with Apply Button ---
        b_cfg = ttk.LabelFrame(self.top, text="Binder Config"); b_cfg.pack(side="left", padx=5)
        ttk.Label(b_cfg, text="Grid:").pack(side="left", padx=2)
        ttk.Entry(b_cfg, width=2, textvariable=self.b_rows).pack(side="left")
        ttk.Label(b_cfg, text="x").pack(side="left")
        ttk.Entry(b_cfg, width=2, textvariable=self.b_cols).pack(side="left")
        tk.Label(b_cfg, text=" Pages:", font=("Arial", 8)).pack(side="left", padx=2)
        ttk.Entry(b_cfg, width=3, textvariable=self.b_total_pages).pack(side="left")
        ttk.Button(b_cfg, text="Apply", command=self.refresh_view).pack(side="left", padx=5)
        
        s_cfg = ttk.LabelFrame(self.top, text="Search Config"); s_cfg.pack(side="left", padx=5)
        ttk.Entry(s_cfg, width=2, textvariable=self.s_rows).pack(side="left")
        ttk.Label(s_cfg, text="x").pack(side="left")
        ttk.Entry(s_cfg, width=2, textvariable=self.s_cols).pack(side="left")
        ttk.Button(s_cfg, text="Apply", command=self.refresh_view).pack(side="left", padx=5)
        
        tools = ttk.LabelFrame(self.top, text="Search Set"); tools.pack(side="left", padx=5)
        self.set_entry = ttk.Entry(tools, width=15); self.set_entry.insert(0, "Surging Sparks"); self.set_entry.pack(side="left", padx=2)
        self.set_entry.bind("<Return>", self.handle_load)
        ttk.Button(tools, text="Load", command=self.handle_load).pack(side="left")
        
        self.prog_frame = ttk.LabelFrame(self.top, text="Set Progress"); self.prog_frame.pack(side="left", padx=5)
        tk.Label(self.prog_frame, textvariable=self.progress_text, font=("Arial", 8)).pack(padx=5)
        
        tk.Checkbutton(self.top, text="🌙 Theme", variable=self.dark_mode, command=self.apply_theme, indicatoron=False).pack(side="right", padx=10)
        
        self.paned = tk.PanedWindow(self.root, orient="horizontal", sashwidth=6); self.paned.pack(fill="both", expand=True)
        self.left_pane = self.create_scrollable_pane(self.paned, "MY BINDER", "binder")
        self.right_pane = self.create_scrollable_pane(self.paned, "SET SEARCH", "search")
        self.status_lbl = tk.Label(self.root, textvariable=self.status_var, relief="flat", anchor="w"); self.status_lbl.pack(side="bottom", fill="x")

    def create_scrollable_pane(self, parent, title, type_name):
        frame = tk.Frame(parent); parent.add(frame, stretch="always")
        header = tk.Frame(frame); header.pack(fill="x", pady=5)
        tk.Label(header, text=title, font=('Segoe UI', 11, 'bold')).pack(side="left", padx=10)
        
        nav = tk.Frame(header); nav.pack(side="right", padx=10)
        
        if type_name == "binder":
            tk.Label(header, text="Filter Binder:", font=("Arial", 8)).pack(side="left", padx=(10, 2))
            self.binder_filter_entry = ttk.Entry(header, width=12, textvariable=self.binder_filter_var)
            self.binder_filter_entry.pack(side="left", padx=2)

            tk.Button(header, text="Empty", bg="#8B0000", fg="white", font=("Arial", 8), command=self.clear_binder).pack(side="left", padx=2)
            tk.Button(header, text="Sort", bg="#4B0082", fg="white", font=("Arial", 8), command=self.sort_binder).pack(side="left", padx=2)
            
            tk.Label(nav, textvariable=self.max_binder_pages_var, font=("Arial", 8)).pack(side="left", padx=5)
            jump = ttk.Entry(nav, width=3, textvariable=self.jump_binder_var)
            jump.pack(side="left", padx=2)
            jump.bind("<Return>", lambda e: self.jump_to_page("binder"))
        else:
            tk.Label(header, text="Filter Set:", font=("Arial", 8)).pack(side="left", padx=(10, 2))
            self.filter_entry = ttk.Entry(header, width=12, textvariable=self.filter_var)
            self.filter_entry.pack(side="left", padx=2)
            
            tk.Button(header, text="+ Full Set", bg="#2E7D32", fg="white", font=("Arial", 8), command=self.add_full_set).pack(side="left", padx=2)
            tk.Label(nav, textvariable=self.max_search_pages_var, font=("Arial", 8)).pack(side="left", padx=5)
            jump = ttk.Entry(nav, width=3, textvariable=self.jump_search_var)
            jump.pack(side="left", padx=2)
            jump.bind("<Return>", lambda e: self.jump_to_page("search"))

        tk.Button(nav, text="<<<", command=lambda: self.change_page(type_name, -1)).pack(side="left", padx=1)
        tk.Button(nav, text=">>>", command=lambda: self.change_page(type_name, 1)).pack(side="left", padx=1)
        
        container = tk.Frame(frame); container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0)
        v_scroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        grid = tk.Frame(canvas); canvas.create_window((0, 0), window=grid, anchor="nw")
        canvas.configure(yscrollcommand=v_scroll.set)
        canvas.pack(side="left", fill="both", expand=True); v_scroll.pack(side="right", fill="y")
        grid.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        return {"grid": grid, "canvas": canvas, "frame": frame, "header": header, "container": container}

    def render_side(self, pane, data, page, is_binder, t, rows, cols):
        for w in pane['grid'].winfo_children(): w.destroy()
        pane['grid'].configure(bg=t["bg"])
        
        pane_width = pane['canvas'].winfo_width() or 700
        card_w = int((pane_width / cols) - 25); per_page = rows * cols; offset = (page - 1) * per_page
        
        try: pages_val = int(self.b_total_pages.get())
        except: pages_val = 1
        total_capacity = rows * cols * pages_val if is_binder else 999999
        
        for i in range(per_page):
            idx = offset + i
            r, c = divmod(i, cols)
            slot = tk.Frame(pane['grid'], bg=t["card_bg"], highlightthickness=2, highlightbackground=t["accent"], width=card_w, height=int(card_w*1.4)+85)
            slot.grid(row=r, column=c, padx=5, pady=5); slot.grid_propagate(False)
            
            if idx < len(data):
                card = data[idx]
                tk.Label(slot, text=f"{card['name']}", bg=t["card_bg"], fg=t["text"], font=('Arial', 7, 'bold'), wraplength=card_w-10).pack(pady=2)
                img_lbl = tk.Label(slot, text="Loading...", bg=t["card_bg"], fg=t["text"])
                img_lbl.pack(expand=True, fill="both")
                
                if is_binder and idx >= total_capacity:
                    warning = tk.Label(img_lbl, text="BEYOND BINDER CAPACITY", fg="white", bg="#D32F2F", font=("Arial", 7, "bold"), padx=5, pady=2)
                    warning.place(relx=0.5, rely=0.05, anchor="n", relwidth=0.95)
                
                threading.Thread(target=lambda c=card, l=img_lbl, w=card_w-10: self.update_label_image(l, self.get_cached_image(c, w)), daemon=True).start()
                
                btn_f = tk.Frame(slot, bg=t["card_bg"]); btn_f.pack(side="bottom", fill="x", pady=2)
                def make_remover(card_to_remove):
                    return lambda: self.remove_card_by_object(card_to_remove)

                tk.Button(btn_f, text="X" if is_binder else "Add", 
                          command=make_remover(card) if is_binder else lambda c=card: self.quick_add(c), 
                          bg="#8B0000" if is_binder else t["btn"], fg="white", font=('Arial', 7)).pack(side="left", fill="x", expand=True)
                
                search_q = f"{card['name']} {card.get('set_id', '').upper()}"
                tk.Button(btn_f, text="Buy", command=lambda q=search_q: webbrowser.open(f"https://www.tcgplayer.com/search/all/product?q={urllib.parse.quote(q)}"), bg="#2B6CB0", fg="white", font=('Arial', 7)).pack(side="left", fill="x", expand=True)
            elif is_binder and idx < total_capacity:
                tk.Label(slot, text=f"Page { (idx // (rows*cols)) + 1}\nSlot {idx+1}", font=("Arial", 8), bg=t["card_bg"], fg=t["accent"]).place(relx=0.5, rely=0.5, anchor="center")

    def apply_theme(self):
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        self.root.configure(bg=t["bg"])
        self.top.configure(bg=t["bg"])
        self.paned.configure(bg=t["bg"])
        for p in [self.left_pane, self.right_pane]:
            p["frame"].configure(bg=t["bg"])
            p["header"].configure(bg=t["bg"])
            p["container"].configure(bg=t["bg"])
            p["canvas"].configure(bg=t["bg"])
            p["grid"].configure(bg=t["bg"])
            for child in p["header"].winfo_children():
                try: child.configure(bg=t["bg"], fg=t["text"])
                except: pass
        self.refresh_view()

    def jump_to_page(self, mode):
        try:
            if mode == "binder": 
                self.binder_page = max(1, int(self.jump_binder_var.get()))
            else: 
                self.search_page = max(1, int(self.jump_search_var.get()))
            self.refresh_view()
        except: pass

    def change_page(self, n, d):
        if n == "binder": 
            self.binder_page = max(1, self.binder_page + d)
            self.jump_binder_var.set(str(self.binder_page))
        else: 
            self.search_page = max(1, self.search_page + d)
            self.jump_search_var.set(str(self.search_page))
        self.refresh_view()

    def refresh_view(self):
        t = self.themes["lunar" if self.dark_mode.get() else "solar"]
        
        per_search = int(self.s_rows.get()) * int(self.s_cols.get())
        max_s = (len(self.display_search_data) + per_search - 1) // per_search
        self.max_search_pages_var.set(f"Max: {max(1, max_s)}")
        
        per_binder = int(self.b_rows.get()) * int(self.b_cols.get())
        max_b = (len(self.display_owned_cards) + per_binder - 1) // per_binder
        self.max_binder_pages_var.set(f"Max: {max(1, max_b)}")

        self.render_side(self.left_pane, self.display_owned_cards, self.binder_page, True, t, int(self.b_rows.get()), int(self.b_cols.get()))
        self.render_side(self.right_pane, self.display_search_data, self.search_page, False, t, int(self.s_rows.get()), int(self.s_cols.get()))
        self.update_progress()

    def update_label_image(self, lbl, photo):
        if photo: self.root.after(0, lambda: lbl.config(image=photo, text="")); lbl.image = photo

    def get_cached_image(self, card, width):
        path = os.path.join(CACHE_DIR, f"{card['id']}.jpg")
        if not os.path.exists(path):
            try: r = requests.get(card['image'], timeout=5); open(path, "wb").write(r.content)
            except: return None
        try: img = Image.open(path).resize((width, int(width * 1.4)), Image.Resampling.LANCZOS); return ImageTk.PhotoImage(img)
        except: return None

    def add_full_set(self): 
        self.owned_cards.extend(self.full_set_data)
        self.apply_binder_filter()
        self.save_collection()
        self.refresh_view()

    def quick_add(self, card): 
        self.owned_cards.append(card)
        self.apply_binder_filter()
        self.save_collection()
        self.refresh_view()

    def remove_card_by_object(self, card_obj):
        if card_obj in self.owned_cards:
            self.owned_cards.remove(card_obj)
            self.apply_binder_filter()
            self.save_collection()
            self.refresh_view()

    def sort_binder(self): 
        self.owned_cards.sort(key=lambda x: x['name'].lower())
        self.apply_binder_filter()
        self.save_collection()
        self.refresh_view()

    def clear_binder(self): 
        self.owned_cards = []
        self.apply_binder_filter()
        self.save_collection()
        self.refresh_view()

    def apply_filter(self):
        q = self.filter_var.get().lower()
        self.display_search_data = [c for c in self.full_set_data if q in c['name'].lower()] if q else self.full_set_data.copy()
        self.search_page = 1
        self.jump_search_var.set("1")
        self.refresh_view()

    def apply_binder_filter(self):
        q = self.binder_filter_var.get().lower()
        self.display_owned_cards = [c for c in self.owned_cards if q in c['name'].lower()] if q else self.owned_cards.copy()
        self.binder_page = 1
        self.jump_binder_var.set("1")
        self.refresh_view()

    def update_progress(self):
        if self.current_set_name:
            owned = len([c for c in self.owned_cards if c.get('set_name') == self.current_set_name])
            self.progress_text.set(f"{self.current_set_name}: {owned}/{len(self.full_set_data)}")

    def reset_and_refresh(self): self.search_page = 1; self.refresh_view()

if __name__ == "__main__":
    root = tk.Tk(); app = TCGApp(root); root.mainloop()