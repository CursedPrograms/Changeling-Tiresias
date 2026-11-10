"""window.py - Changeling Tiresias's window, in Changeling's look (customtkinter, the Cursed pink).

Open a photo: the face is found and its gender read, and the opposite is picked for you (still yours to
change). Press Swap: the work runs on its own thread, with a completion bar while it learns your face
(Balanced and Best fine-tune the generator on it, so the result still looks like you). Save writes the
result next to the photo, or wherever you choose.
"""
import os
import threading
import time
import tkinter as tk
import webbrowser
from gallery import remember, show as show_gallery
from tkinter import filedialog

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "Changeling Tiresias"
TAGLINE = "the other you: a face, swapped to the other gender"
GITHUB = "https://github.com/CursedPrograms/Changeling-Tiresias"
KOFI = "https://ko-fi.com/cursedentertainment"
PINK = "#e0408a"

BLUE, BLUE_HOVER = "#007ab7", "#005184"     # the Cursed site's blue: the important buttons, and "male"


def gender_tint(seg):
    """Colours a gender selector by what's picked: female pink, male blue, anything else the usual pink."""
    def tint(value=None):
        v = (value or seg.get() or "").lower()
        colour = PINK if ("female" in v or "woman" in v) else BLUE if ("male" in v or v == "man") else PINK
        seg.configure(selected_color=colour, selected_hover_color=colour)
    old = seg.cget("command")
    seg.configure(command=lambda v: (tint(v), old(v) if old else None))
    tint()

QUALITY_STEPS = {"Fast": 0, "Balanced": 100, "Best": 250}
# what the result is: the swapped square on its own (default), or pasted back into the photo
RESULTS = {"Face frame": ("frame", False), "Whole photo": ("photo", False), "Photo, own hair": ("photo", True)}
IMAGE_TYPES = [("Pictures", "*.png *.jpg *.jpeg *.webp *.bmp *.jfif"), ("All files", "*.*")]


def read_rgb(path):
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    return None if image is None else cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def write_rgb(path, image):
    ok, buf = cv2.imencode(os.path.splitext(path)[1] or ".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    if ok:
        buf.tofile(path)
    return ok



def set_logo(root, here):
    """The Changeling logo as the window's icon (title bar and taskbar). customtkinter puts its own icon in
    about 200 ms after the window opens, so this goes in just after it."""
    ico, png = os.path.join(here, "logo.ico"), os.path.join(here, "logo.png")

    def apply():
        try:
            if os.name == "nt" and os.path.exists(ico):
                root.iconbitmap(ico)
            elif os.path.exists(png):
                root._logo_icon = tk.PhotoImage(file=png)
                root.iconphoto(True, root._logo_icon)
        except tk.TclError:
            pass
    root.after(300, apply)


def logo_image(here, size=56):
    """The logo for the sidebar, or None."""
    png = os.path.join(here, "logo.png")
    if not os.path.exists(png):
        return None
    return ctk.CTkImage(Image.open(png), size=(size, size))

class Window:
    def __init__(self, make_swapper, device=None):
        self.make_swapper = make_swapper
        self.device = device
        self.swapper = None
        self.photo = None            # RGB
        self.photo_path = None
        self.result = None           # SwapResult
        self.job = None
        self.state = {"busy": False, "stage": "", "done": 0, "total": 0, "t0": 0.0, "message": ""}
        self.lock = threading.Lock()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme(os.path.join(HERE, "theme.json"))
        self.root = ctk.CTk()
        set_logo(self.root, HERE)
        self.root.title(NAME)
        self.root.geometry("1280x780")
        self.root.minsize(980, 620)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self._build()
        self.root.bind("<Control-o>", lambda e: self.open())
        self.root.bind("<Control-s>", lambda e: self.save())
        self.root.bind("<Return>", lambda e: self.swap())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.after(100, self.watch)
        self._run(self._load_models, "Loading the models")

    # ---- the window
    def _build(self):
        stage = ctk.CTkFrame(self.root, corner_radius=12)
        stage.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=14)
        stage.grid_columnconfigure((0, 1), weight=1, uniform="half")
        stage.grid_rowconfigure(1, weight=1)
        for col, text in enumerate(("Before", "After")):
            ctk.CTkLabel(stage, text=text.upper(), text_color="gray50",
                         font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=col, pady=(8, 0))
        self.before = tk.Label(stage, bg="#16161a", bd=0, text="Open a photo  (Ctrl+O)", fg="gray60",
                               font=("Segoe UI", 12), cursor="hand2")
        self.before.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=8)
        self.before.bind("<Button-1>", lambda e: self.open())
        self.after_view = tk.Label(stage, bg="#16161a", bd=0, fg="gray60", font=("Segoe UI", 12))
        self.after_view.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=8)
        self.before.bind("<Configure>", lambda e: self.root.after_idle(self._refresh))

        side = ctk.CTkFrame(self.root, width=310, corner_radius=12)
        side.grid(row=0, column=1, sticky="ns", padx=(7, 14), pady=14)
        side.grid_propagate(False)
        logo = logo_image(HERE)
        if logo is not None:
            ctk.CTkLabel(side, image=logo, text="").pack(anchor="w", padx=14, pady=(12, 0))
        ctk.CTkLabel(side, text="CHANGELING", text_color="gray55",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=14, pady=(12, 0))
        ctk.CTkLabel(side, text="Tiresias", font=ctk.CTkFont(size=24, weight="bold"), text_color=PINK).pack(anchor="w", padx=14)
        ctk.CTkLabel(side, text=TAGLINE, text_color="gray60", wraplength=280, justify="left").pack(anchor="w", padx=14)

        ctk.CTkButton(side, text="Open photo  (Ctrl+O)", command=self.open).pack(fill="x", padx=14, pady=(16, 4))
        self.detected = ctk.CTkLabel(side, text="", text_color="gray70", wraplength=280, justify="left")
        self.detected.pack(anchor="w", padx=14)

        self._section(side, "Swap")
        self.direction = ctk.CTkSegmentedButton(side, values=["Auto", "To female", "To male"])
        self.direction.set("Auto")
        self.direction.pack(fill="x", padx=14, pady=4)
        gender_tint(self.direction)
        self.strength = self._slider(side, "Strength", 25, 200, 100)
        self._section(side, "Result")
        self.result_mode = ctk.CTkSegmentedButton(side, values=list(RESULTS))
        self.result_mode.set("Face frame")
        self.result_mode.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(side, text="Face frame: the swapped square, new hair and all. Whole photo: pasted back "
                     "(long hair outside the square stays). Own hair: only the face changes.",
                     text_color="gray55", wraplength=280, justify="left").pack(anchor="w", padx=14)

        self._section(side, "Quality")
        self.quality = ctk.CTkSegmentedButton(side, values=list(QUALITY_STEPS))
        self.quality.set("Balanced")
        self.quality.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(side, text="Balanced and Best learn your face first, so the result still looks like you "
                     "(about 1 and 3 minutes). Fast takes seconds.", text_color="gray55",
                     wraplength=280, justify="left").pack(anchor="w", padx=14)

        self.swap_btn = ctk.CTkButton(side, fg_color=BLUE, hover_color=BLUE_HOVER, text="Swap  (Enter)", height=42,
                                      font=ctk.CTkFont(size=15, weight="bold"), command=self.swap)
        self.swap_btn.pack(fill="x", padx=14, pady=(18, 6))
        self.bar = ctk.CTkProgressBar(side, mode="determinate")
        self.bar.set(0)
        self.bar.pack(fill="x", padx=14, pady=(4, 2))
        self.status = ctk.CTkLabel(side, text="", text_color="gray65", wraplength=280, justify="left")
        self.status.pack(anchor="w", padx=14)
        row = ctk.CTkFrame(side, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(10, 0))
        self.save_btn = ctk.CTkButton(row, text="Save  (Ctrl+S)", command=self.save, state="disabled")
        self.save_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(row, text="Gallery", width=80, command=self.gallery).pack(side="left", padx=(4, 4))
        self.face_btn = ctk.CTkButton(row, text="Close-up", width=90, command=self.show_closeup, state="disabled")
        self.face_btn.pack(side="left")

        foot = ctk.CTkFrame(side, fg_color="transparent")
        foot.pack(side="bottom", fill="x", padx=14, pady=(0, 10))
        links = ctk.CTkFrame(foot, fg_color="transparent")
        links.pack(anchor="w")
        for text, url in (("GitHub", GITHUB), ("Ko-fi", KOFI)):
            l = ctk.CTkLabel(links, text=text, text_color=("#c2186b", "#f29cc0"), cursor="hand2")
            l.pack(side="left", padx=(0, 14))
            l.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
        ctk.CTkLabel(foot, text="© Cursed Entertainment 2026", text_color="gray45").pack(anchor="w")

    def _section(self, parent, text):
        ctk.CTkLabel(parent, text=text.upper(), text_color="gray50",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=14, pady=(14, 1))

    def _slider(self, parent, text, lo, hi, value):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(6, 0))
        ctk.CTkLabel(row, text=text).pack(side="left")
        shown = ctk.CTkLabel(row, text=f"{value}%", text_color="gray60")
        shown.pack(side="right")
        s = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=(hi - lo) // 5,
                          command=lambda v: shown.configure(text=f"{int(v)}%"))
        s.set(value)
        s.pack(fill="x", padx=14, pady=(0, 4))
        return s

    def _show(self, label, image):
        if image is None:
            label.configure(image="")
            label.image = None
            return
        w, h = max(label.winfo_width(), 64), max(label.winfo_height(), 64)
        ih, iw = image.shape[:2]
        k = min(w / iw, h / ih)
        small = cv2.resize(image, (max(int(iw * k), 1), max(int(ih * k), 1)), interpolation=cv2.INTER_AREA)
        photo = ImageTk.PhotoImage(Image.fromarray(small))
        label.configure(image=photo, text="")
        label.image = photo

    def _refresh(self):
        self._show(self.before, self.photo)
        self._show(self.after_view, self.result.image if self.result else None)

    # ---- the jobs, on their own thread; the window follows self.state
    def _run(self, work, stage):
        with self.lock:
            self.state.update(busy=True, stage=stage, done=0, total=0, t0=time.monotonic(), message="")
        self.swap_btn.configure(state="disabled")
        self.job = threading.Thread(target=self._guard, args=(work,), daemon=True)
        self.job.start()

    def _guard(self, work):
        try:
            message = work()
        except Exception as e:
            message = f"Couldn't: {e}"
        with self.lock:
            self.state.update(busy=False, message=message or "")

    def _step(self, done, total, _loss=None):
        with self.lock:
            self.state.update(stage="Learning your face", done=done, total=total)

    def watch(self):
        with self.lock:
            s = dict(self.state)
        if s["busy"]:
            if s["total"]:
                if self.bar.cget("mode") != "determinate":
                    self.bar.stop()
                    self.bar.configure(mode="determinate")
                frac = s["done"] / s["total"]
                self.bar.set(frac)
                text = f"{s['stage']}  {s['done']} / {s['total']}  {frac:.0%}"
                elapsed = time.monotonic() - s["t0"]
                if s["done"] and elapsed > 1:
                    left = int(elapsed / s["done"] * (s["total"] - s["done"]))
                    text += f"  {left // 60}:{left % 60:02d} left"
            else:
                if self.bar.cget("mode") != "indeterminate":
                    self.bar.configure(mode="indeterminate")
                    self.bar.start()
                text = s["stage"] + " ..."
            self.status.configure(text=text)
        elif self.job is not None and not self.job.is_alive():
            self.job = None
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self.bar.set(1 if self.result is not None else 0)
            self.status.configure(text=s["message"])
            self.swap_btn.configure(state="normal" if self.swapper else "disabled")
            self.save_btn.configure(state="normal" if self.result else "disabled")
            self.face_btn.configure(state="normal" if self.result else "disabled")
            self._refresh()
        self.root.after(100, self.watch)

    def _load_models(self):
        self.swapper = self.make_swapper(self.device)
        return "Ready: open a photo."

    # ---- what the buttons do
    def open(self, path=None):
        path = path or filedialog.askopenfilename(title="A photo with a face", filetypes=IMAGE_TYPES)
        if not path:
            return
        image = read_rgb(path)
        if image is None:
            self.status.configure(text=f"Can't read {os.path.basename(path)}")
            return
        self.photo, self.photo_path, self.result = image, path, None
        self.save_btn.configure(state="disabled")
        self.face_btn.configure(state="disabled")
        self._refresh()
        self.detect()

    def detect(self):
        if self.swapper is None or self.photo is None:
            return
        try:
            gender, confidence = self.swapper.detect_gender(self.photo)
        except ValueError as e:
            self.detected.configure(text=str(e))
            return
        choice = "To female" if gender == "male" else "To male"
        self.direction.set(choice)
        self.detected.configure(text=f"Looks {gender} ({confidence:.0%}), so {choice.lower()} is picked.")

    def swap(self):
        if self.swapper is None or self.photo is None or self.job is not None:
            if self.photo is None:
                self.open()
            return
        target = {"Auto": "auto", "To female": "female", "To male": "male"}[self.direction.get()]
        strength = self.strength.get() / 100
        steps = QUALITY_STEPS[self.quality.get()]
        image = self.photo
        output, keep_hair = RESULTS[self.result_mode.get()]

        def work():
            with self.lock:
                self.state["stage"] = "Swapping"
            self.result = self.swapper.swap(image, target, strength, steps, self._step, keep_hair=keep_hair, output=output)
            return f"Done: {self.result.detected} to {self.result.target}."
        self.result = None
        self._run(work, "Reading the face")

    def gallery(self):
        """Everything made with the Changelings (saving still asks where; the gallery lists it too)."""
        show_gallery(self.root, "Tiresias")

    def save(self):
        if self.result is None:
            return
        stem, _ = os.path.splitext(os.path.basename(self.photo_path or "photo.png"))
        path = filedialog.asksaveasfilename(title="Save the result", defaultextension=".png",
                                            initialdir=os.path.dirname(self.photo_path or HERE),
                                            initialfile=f"{stem}_{self.result.target}.png",
                                            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
        if path and write_rgb(path, self.result.image):
            self.status.configure(text=f"Saved {os.path.basename(path)}")
            remember(path, "Tiresias")

    def show_closeup(self):
        if self.result is None:
            return
        top = ctk.CTkToplevel(self.root)
        top.title("Close-up: the photo, the reconstruction, the result")
        strip = np.concatenate([self.result.aligned, self.result.reconstruction, self.result.edited], axis=1)
        strip = cv2.resize(strip, (1200, 400), interpolation=cv2.INTER_AREA)
        img = ctk.CTkImage(Image.fromarray(strip), size=(1200, 400))
        ctk.CTkLabel(top, image=img, text="").pack(padx=10, pady=10)
        top.after(100, top.lift)

    def run(self, path=None):
        if path:
            self.root.after(300, lambda: self.open(path))
        self.root.mainloop()
